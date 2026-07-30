"""E9.2/E9.3/E9.5: the camera-ready paper tables must stay tied to their JSONs.

`scripts/cr_paper_tables.py` regenerates the generation funnel, the human
validation contingency table, the open-universe exposure matrix, the
leave-own-family-out leaderboard, the decay table and the distractor-strategy
ablation from committed numbers files. The point of the script is that the paper
cannot drift from the data silently, so the load-bearing test is the `--check`
round trip against the real `paper/sections/{appendix,results}.tex`. The row
builders are unit-tested separately against fixtures so a formatting change
fails with a readable diff rather than as a wall of missing rows.

The E9.3 and E9.5 builders also assert the claims the paper makes about them
(Spearman, which pairs swap, the pooled decay rate, the pre-registered
hard-negative contrast), so those assertions are themselves tested against a
deliberately wrong expectation --- a check that cannot fail is not a check.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cr_paper_tables  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _lofo_fixture(spearman: float = 0.5) -> dict:
    """Three models with one adjacent swap: headline A>C>B, LOFO A>B>C."""
    return {
        "lofo": {
            "models": [
                {"model": "alpha", "headline": 10.0, "lofo": 10.0, "family_authored": True},
                {"model": "beta", "headline": 8.0, "lofo": 9.0, "family_authored": True},
                {"model": "gamma", "headline": 9.0, "lofo": 8.0, "family_authored": False},
            ],
            "expected": {"spearman": spearman, "swapped_pairs": [["beta", "gamma"]]},
        }
    }


def _decay_fixture(pooled: dict | None = None) -> dict:
    return {
        "decay": {
            "rows": [
                {"domain": "alpha", "servers": 2, "calls": 10, "identical": 50, "drifted": 50, "broken": 0},
                {"domain": "beta", "servers": 3, "calls": 40, "identical": 10, "drifted": 40, "broken": 50},
            ],
            "pooled_expected": pooled
            or {"servers": 5, "calls": 50, "identical": 18, "drifted": 42, "broken": 40},
        }
    }


def test_funnel_rows_derive_yields_from_counts(tmp_path, monkeypatch):
    src = tmp_path / "e9.2_numbers.json"
    src.write_text(
        json.dumps(
            {
                "funnel": {
                    "goals_issued": 100,
                    "traces_recorded": 200,
                    "specs_parsed": 100,
                    "validator_valid": 50,
                }
            }
        )
    )
    monkeypatch.setattr(cr_paper_tables, "E9_2", src)
    rows = cr_paper_tables.funnel_rows()
    assert len(rows) == 4
    # Yields are computed, never transcribed: 100/200 and 50/100.
    assert "50.0" in rows[2]
    assert "50.0" in rows[3]


def test_confusion_rows_close_the_two_by_two(tmp_path, monkeypatch):
    src = tmp_path / "e4.6_numbers.json"
    src.write_text(json.dumps({"scorer_vs_human": {"fp_n": 2, "fp_d": 10, "fn_n": 3, "fn_d": 20}}))
    monkeypatch.setattr(cr_paper_tables, "E4_6", src)
    rows = cr_paper_tables.confusion_rows()
    assert rows[0].startswith("automatic pass & 8 & 2  & 10")
    assert rows[1].startswith("automatic fail & 3 & 17 & 20")
    # Margins must add up, or the table is not a contingency table.
    assert rows[2].startswith("total          & 11 & 19 & 30")


def test_exposure_rows_mark_uncovered_cells(tmp_path, monkeypatch):
    src = tmp_path / "e9.1_numbers.json"
    src.write_text(json.dumps({"minimax-m3|flat": {"pass_pct": 36.0, "passed": 54, "n": 150}}))
    monkeypatch.setattr(cr_paper_tables, "E9_1", src)
    rows = cr_paper_tables.exposure_rows()
    flat = next(r for r in rows if r.startswith(r"\texttt{flat}"))
    # A model without that cell is "---", never an implied zero or a blank.
    assert flat.count("---") == 3
    assert "36.0" in flat


def test_lofo_rows_order_by_lofo_and_show_rank_movement(tmp_path, monkeypatch):
    src = tmp_path / "e9.3_numbers.json"
    src.write_text(json.dumps(_lofo_fixture()))
    monkeypatch.setattr(cr_paper_tables, "E9_3", src)
    rows = cr_paper_tables.lofo_rows()
    # Ordered by the LOFO column, not the headline one.
    assert [r.split(" &")[0] for r in rows] == ["alpha", "beta", r"gamma$^{\dagger}$"]
    # An unmoved model shows a bare rank; a swapped pair shows both ranks.
    assert rows[0].endswith(r"& 1 \\")
    assert rows[1].endswith(r"& $3 \to 2$ \\")
    assert rows[2].endswith(r"& $2 \to 3$ \\")


def test_lofo_rows_reject_a_stale_spearman_claim(tmp_path, monkeypatch):
    src = tmp_path / "e9.3_numbers.json"
    src.write_text(json.dumps(_lofo_fixture(spearman=0.9)))
    monkeypatch.setattr(cr_paper_tables, "E9_3", src)
    with pytest.raises(AssertionError, match="Spearman"):
        cr_paper_tables.lofo_rows()


def test_decay_pooled_row_is_recomputed_from_the_per_domain_rows(tmp_path, monkeypatch):
    src = tmp_path / "e9.3_numbers.json"
    src.write_text(json.dumps(_decay_fixture()))
    monkeypatch.setattr(cr_paper_tables, "E9_3", src)
    rows = cr_paper_tables.decay_rows()
    # Call-weighted, not a mean of the rows: (10*50 + 40*10) / 50 = 18, not 30.
    # Servers add up instead, because the domains partition them.
    assert rows[-1] == r"all & 5 & 50 & \textbf{18\%} & 42\% & 40\% \\"


def test_decay_pooled_broken_keeps_a_decimal_when_an_integer_would_read_as_zero(tmp_path, monkeypatch):
    src = tmp_path / "e9.3_numbers.json"
    rows = [
        {"domain": "alpha", "servers": 2, "calls": 900, "identical": 33, "drifted": 67, "broken": 0},
        {"domain": "beta", "servers": 3, "calls": 100, "identical": 33, "drifted": 63, "broken": 4},
    ]
    pooled = {"servers": 5, "calls": 1000, "identical": 33, "drifted": 67, "broken": 0.4}
    src.write_text(json.dumps({"decay": {"rows": rows, "pooled_expected": pooled}}))
    monkeypatch.setattr(cr_paper_tables, "E9_3", src)
    # (900*0 + 100*4) / 1000 = 0.4, which an integer round would flatten to a
    # bare 0% and misreport near-absent breakage as none at all.
    assert cr_paper_tables.decay_rows()[-1].endswith(r"0.4\% \\")


def test_decay_rows_reject_a_pooled_rate_the_rows_do_not_support(tmp_path, monkeypatch):
    src = tmp_path / "e9.3_numbers.json"
    src.write_text(
        json.dumps(_decay_fixture({"servers": 5, "calls": 50, "identical": 30, "drifted": 42, "broken": 40}))
    )
    monkeypatch.setattr(cr_paper_tables, "E9_3", src)
    with pytest.raises(AssertionError, match="pooled"):
        cr_paper_tables.decay_rows()


def _distractor_fixture(delta_pp: float = 0.57, supported: bool = False) -> dict:
    cells = {
        s: {"sae_n": 0, "sae_pct": 0.0, "pass_n": 0, "pass_pct": 50.0}
        for s in ("random", "cross_domain", "same_name", "sibling", "stratified")
    }
    cells["hard_neg"] = {"sae_n": 2, "sae_pct": delta_pp, "pass_n": 0, "pass_pct": 50.0}
    return {
        "g3_2_ablation": {"glm-5.1": cells, "deepseek-v4-pro": cells},
        "g3_2_H1_preregistered": {
            "glm-5.1": {"delta_pp": delta_pp, "supported": supported},
            "deepseek-v4-pro": {"delta_pp": delta_pp, "supported": supported},
        },
    }


def test_distractor_rows_cover_all_six_strategies(tmp_path, monkeypatch):
    src = tmp_path / "e8.9_numbers.json"
    src.write_text(json.dumps(_distractor_fixture()))
    monkeypatch.setattr(cr_paper_tables, "E8_9", src)
    rows = cr_paper_tables.distractor_rows()
    # Six strategies plus the contrast row: the ablation lost in the paper reset
    # had only four, so a regression to four rows fails here.
    assert len(rows) == 7
    assert r"\textsf{sibling}" in rows[4]
    assert r"\textsf{stratified}" in rows[5]
    # The contrast is derived from the cells, not read off the pre-registration.
    assert rows[6].count(r"$+0.6$\,pp") == 2


def test_distractor_rows_reject_a_result_that_would_support_the_prereg(tmp_path, monkeypatch):
    src = tmp_path / "e8.9_numbers.json"
    src.write_text(json.dumps(_distractor_fixture(delta_pp=20.0, supported=True)))
    monkeypatch.setattr(cr_paper_tables, "E8_9", src)
    # A hard_neg effect clearing the 15pp threshold would invalidate the
    # paragraph the table is cited from, so the builder refuses to emit it.
    with pytest.raises(AssertionError, match="supported|threshold"):
        cr_paper_tables.distractor_rows()


def test_generated_tables_match_the_committed_paper():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/cr_paper_tables.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    # Pin the table count so dropping a table from the registry cannot pass silently.
    assert f"across {len(cr_paper_tables.TABLES)} tables" in proc.stdout
    assert len(cr_paper_tables.TABLES) == 6
