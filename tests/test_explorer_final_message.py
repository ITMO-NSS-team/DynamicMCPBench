"""Final-message fallback for budget-exhausted explorations.

When the agent uses up its whole budget still calling tools (or ends on an empty
turn), ``final_message`` would stay ``None`` and every ``value_produced`` checkpoint
phantom-failed with 'no final_assistant_message stashed' — a model-dependent penalty
for agents that keep calling tools to the budget edge. The fallback exposes the last
assistant text the agent produced.
"""

from dmcp.explorer import _last_assistant_text


def test_returns_last_assistant_text_even_with_tool_calls():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "looking into it", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "result"},
        {"role": "assistant", "content": "the answer is 42", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "tool_call_id": "2", "content": "more"},
    ]
    assert _last_assistant_text(messages) == "the answer is 42"


def test_skips_empty_assistant_turns():
    messages = [
        {"role": "assistant", "content": "earlier text", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "r"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2"}]},
        {"role": "tool", "tool_call_id": "2", "content": "r"},
    ]
    assert _last_assistant_text(messages) == "earlier text"


def test_none_when_no_assistant_text():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "r"},
    ]
    assert _last_assistant_text(messages) is None
