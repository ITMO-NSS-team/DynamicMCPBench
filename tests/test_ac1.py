"""CR 5.2 / E9.13 — the agreement coefficients the paper publishes.

The raw annotations are study data and are git-ignored (they live in the HF
dataset), so these tests pin the *math* on synthetic tables with hand-computed
values, plus the kappa-set selection rule that decides which items the math
sees. The headline case is the prevalence paradox: on a near-unanimous axis
Fleiss kappa collapses to ~0 while raw agreement is 99% — that is the entire
justification for reporting AC1 in the paper, so it is a regression test rather
than a footnote.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ac1  # noqa: E402  (script imported as a module for testing)


def test_perfect_agreement_is_one_on_both_coefficients():
    table = [[3, 0], [0, 3], [3, 0]]
    assert ac1.percent_agreement(table) == pytest.approx(1.0)
    assert ac1.fleiss_kappa(table) == pytest.approx(1.0)
    assert ac1.gwet_ac1(table) == pytest.approx(1.0)


def test_hand_computed_two_item_example():
    """One unanimous item, one split item, two raters, two categories."""
    table = [[2, 0], [1, 1]]
    assert ac1.percent_agreement(table) == pytest.approx(0.5)
    # p_e(Fleiss) = .75^2 + .25^2 = .625 -> (0.5 - .625)/(1 - .625)
    assert ac1.fleiss_kappa(table) == pytest.approx(-1 / 3)
    # p_e(Gwet)   = (.75*.25 + .25*.75)/(2-1) = .375 -> (0.5 - .375)/(1 - .375)
    assert ac1.gwet_ac1(table) == pytest.approx(0.2)


def test_the_prevalence_paradox_is_why_the_paper_reports_ac1():
    """99 unanimous items + 1 split: 99% raw agreement, yet kappa reads ~0."""
    table = [[2, 0]] * 99 + [[1, 1]]
    assert ac1.percent_agreement(table) == pytest.approx(0.99)
    assert ac1.fleiss_kappa(table) == pytest.approx(-0.005, abs=0.001)
    assert ac1.gwet_ac1(table) == pytest.approx(0.990, abs=0.001)


def test_ac1_needs_at_least_two_categories():
    assert ac1.gwet_ac1([[3], [3]]) != ac1.gwet_ac1([[3], [3]])  # NaN


def test_items_with_a_single_rating_do_not_enter_the_average():
    """A lone rating carries no pairwise information; it must not count as agreement."""
    both = ac1.percent_agreement([[2, 0], [1, 0]])
    only_pair = ac1.percent_agreement([[2, 0]])
    assert both == pytest.approx(only_pair)


def test_rating_table_drops_off_domain_labels():
    table = ac1.rating_table([["yes", "no", "maybe"], ["yes", None, "yes"]], ["yes", "no"])
    assert table == [[1, 1], [2, 0]]


def _card(task: str, rater: str, *, kappa: bool = True, **ann):
    base = {"valid": "yes", "ref_ok": "yes", "grader_ok": "yes"}
    base.update(ann)
    return {"task_id": task, "rater": rater, "is_kappa": kappa, "ann": base}


def test_kappa_set_keeps_only_tasks_every_rater_saw():
    rows = [
        _card("t1", "a"),
        _card("t1", "b"),
        _card("t2", "a"),  # only one rater -> excluded
        _card("t3", "a"),
        _card("t3", "b"),
        _card("t4", "a", kappa=False),  # not a kappa item at all
        _card("t4", "b", kappa=False),
    ]
    full, nr = ac1.kappa_set(rows)
    assert nr == 2
    assert sorted(full) == ["t1", "t3"]


def test_kappa_set_is_empty_without_kappa_items():
    full, nr = ac1.kappa_set([_card("t1", "a", kappa=False)])
    assert full == {} and nr == 0


def test_agreement_report_covers_the_three_published_axes():
    rows = []
    for task in ("t1", "t2", "t3"):
        for rater in ("a", "b", "c"):
            rows.append(_card(task, rater))
    rows.append(_card("t4", "a", ref_ok="partial"))  # partial rater set, dropped
    rep = ac1.agreement_report(rows)

    assert rep["raters"] == 3
    assert rep["kappa_set_tasks"] == 3
    assert sorted(rep["fields"]) == ["grader_agreement", "reference_correctness", "validity"]
    assert rep["fields"]["reference_correctness"]["domain"] == ["yes", "partial", "no"]
    for f in rep["fields"].values():
        assert f["items"] == 3
        assert f["ac1"] == pytest.approx(1.0)


def test_load_rows_keeps_only_annotated_cards(tmp_path: Path):
    p = tmp_path / "annotate_x.jsonl"
    p.write_text(
        json.dumps({"task_id": "t1", "ann": None})
        + "\n"
        + json.dumps(_card("t2", "a"))
        + "\n\n"  # blank line tolerated
        + json.dumps(_card("t3", "a"))
        + "\n",
        encoding="utf-8",
    )
    rows = ac1.load_rows([str(p)])
    assert [r["task_id"] for r in rows] == ["t2", "t3"]


def test_check_against_numbers_flags_a_drifted_figure(tmp_path: Path):
    rows = [_card(t, r) for t in ("t1", "t2") for r in ("a", "b")]
    rep = ac1.agreement_report(rows)  # every AC1 is 1.0

    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"ac1": {"validity": 1.0, "reference_correctness": 1.0, "grader_agreement": 1.0}}),
        encoding="utf-8",
    )
    assert ac1.check_against_numbers(rep, good) == []

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"ac1": {"validity": 0.5, "reference_correctness": 1.0}}),
        encoding="utf-8",
    )
    problems = ac1.check_against_numbers(rep, bad)
    assert any("validity" in p for p in problems)
    assert any("grader_agreement" in p and "absent" in p for p in problems)


def test_published_ac1_block_is_present_and_in_range():
    """Guards the committed numbers the paper renders from (`paper/regenerate.py`)."""
    data = json.loads(ac1.NUMBERS.read_text(encoding="utf-8"))
    published = {k: v for k, v in data["ac1"].items() if not k.startswith("_")}
    assert sorted(published) == ["grader_agreement", "reference_correctness", "validity"]
    assert all(-1.0 <= float(v) <= 1.0 for v in published.values())


def test_missing_annotations_exit_with_a_pointer_not_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert ac1.main([]) == 2
    assert "--pull" in capsys.readouterr().err
