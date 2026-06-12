"""Final-message scoring is STRICT about non-completion.

An agent that ran out of budget still calling tools never delivered an answer, so it
must FAIL ``value_produced`` — it is NOT credited with mid-reasoning text (that would
count a non-completion as a pass). A voluntary completion whose final turn had empty
content does fall back to its last assistant text.
"""

from dmcp.explorer import _last_assistant_text, _resolve_final_message


def _msgs():
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "the answer is 42", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "r"},
    ]


def test_explicit_final_message_is_kept():
    assert _resolve_final_message("done: X", "completed", _msgs()) == "done: X"


def test_budget_exhausted_gets_no_fallback():
    # ran out of budget mid tool-calling → no delivered answer → stays None → fails
    assert _resolve_final_message(None, "budget_exhausted", _msgs()) is None
    assert _resolve_final_message("", "budget_exhausted", _msgs()) is None


def test_voluntary_completion_falls_back_to_last_text():
    assert _resolve_final_message(None, "completed", _msgs()) == "the answer is 42"
    assert _resolve_final_message("", "no_tools_called", _msgs()) == "the answer is 42"


def test_last_assistant_text_helper():
    assert _last_assistant_text(_msgs()) == "the answer is 42"
    assert _last_assistant_text([{"role": "user", "content": "x"}]) is None
