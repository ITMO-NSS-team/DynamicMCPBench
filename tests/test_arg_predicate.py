"""Arg-predicate matching must look *inside* list/dict arguments.

Regression guard for the evaluator bug where ``contains``/``regex``/``starts_with``
silently failed on any non-string argument (e.g. ``categories=["cs.AI", "cs.CR"]``,
``pmids=[...]``, a nested ``filters={...}``) — failing the gold trace and every
correct candidate alike, depressing pass rates on list-arg tasks.
"""

from dmcp.evaluator import _arg_predicate_matches
from dmcp.spec import ArgPredicate, ArgValueMatch


def _pred(**must_match: dict) -> ArgPredicate:
    return ArgPredicate(must_match={k: ArgValueMatch(**v) for k, v in must_match.items()})


def test_contains_matches_inside_list_arg():
    pred = _pred(categories={"contains": "cs.CR"})
    assert _arg_predicate_matches(pred, {"categories": ["cs.AI", "cs.CR", "cs.LG"]})
    assert not _arg_predicate_matches(pred, {"categories": ["cs.AI", "cs.LG"]})


def test_regex_matches_inside_list_arg():
    pred = _pred(pmids={"regex": "40200444|41930073"})
    assert _arg_predicate_matches(pred, {"pmids": ["40200444", "41930073", "42044287"]})
    assert not _arg_predicate_matches(pred, {"pmids": ["99999999"]})


def test_contains_matches_inside_nested_dict_arg():
    pred = _pred(filters={"contains": "EA"})
    assert _arg_predicate_matches(pred, {"filters": {"geo": ["EA"], "freq": ["Q"]}})
    assert not _arg_predicate_matches(pred, {"filters": {"geo": ["US"]}})


def test_starts_with_matches_a_list_element():
    pred = _pred(tags={"starts_with": "cs."})
    assert _arg_predicate_matches(pred, {"tags": ["math.PR", "cs.AI"]})
    assert not _arg_predicate_matches(pred, {"tags": ["math.PR", "stat.ML"]})


def test_string_args_behaviour_unchanged():
    pred = _pred(query={"contains": "security"})
    assert _arg_predicate_matches(pred, {"query": "ai security review"})
    assert not _arg_predicate_matches(pred, {"query": "weather forecast"})
    rx = _pred(dataset_id={"regex": "^HEALTH_EXPENDITURE$"})
    assert _arg_predicate_matches(rx, {"dataset_id": "HEALTH_EXPENDITURE"})
    assert not _arg_predicate_matches(rx, {"dataset_id": "PUBLIC_HOSPITALS"})


def test_must_include_exact_still_required():
    pred = ArgPredicate(must_include={"sort_by": "date", "max_results": 15})
    assert _arg_predicate_matches(pred, {"sort_by": "date", "max_results": 15, "q": "x"})
    assert not _arg_predicate_matches(pred, {"sort_by": "relevance", "max_results": 15})


def test_missing_key_fails():
    pred = _pred(categories={"contains": "cs.CR"})
    assert not _arg_predicate_matches(pred, {"other": ["cs.CR"]})


def test_empty_predicate_matches_anything():
    assert _arg_predicate_matches(None, {"anything": 1})
    assert _arg_predicate_matches(ArgPredicate(), {"anything": 1})


def test_malformed_regex_does_not_crash():
    # A distilled regex with a global flag not at the start is invalid in py3.11+;
    # it must be treated as 'no match', not crash the whole eval run.
    pred = _pred(notes={"regex": "(?s).*a.*|(?s).*b.*"})
    assert not _arg_predicate_matches(pred, {"notes": "anything"})
    assert not _arg_predicate_matches(pred, {"notes": ["x", "y"]})
