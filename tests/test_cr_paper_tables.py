"""E9.2: the three camera-ready appendix tables must stay tied to their JSONs.

`scripts/cr_paper_tables.py` regenerates the generation funnel, the human
validation contingency table and the open-universe exposure matrix from
committed numbers files. The point of the script is that the paper cannot drift
from the data silently, so the load-bearing test is the `--check` round trip
against the real `paper/sections/appendix.tex`. The row builders are unit-tested
separately against fixtures so a formatting change fails with a readable diff
rather than as a wall of missing rows.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cr_paper_tables  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


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


def test_generated_tables_match_the_committed_paper():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/cr_paper_tables.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
