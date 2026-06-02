"""E3 Phase B: arg synthesis + destructive detection + content-error gate +
dependency-harvest (all offline)."""

from __future__ import annotations

from dmcp.verify import (
    _content_error_signal,
    _harvest_values,
    _result_json,
    is_destructive,
    synthesize_args,
)


def _text(t: str) -> dict:
    return {"content": [{"type": "text", "text": t}]}


def test_is_destructive_snake_and_camel():
    assert is_destructive("delete_file")
    assert is_destructive("db_drop_table")
    assert is_destructive("removeUser")  # camelCase
    assert is_destructive("resetPassword")
    assert not is_destructive("get_issue")
    assert not is_destructive("search")
    assert not is_destructive("list_repositories")
    assert not is_destructive("create_branch")  # create is not destructive


def test_synthesize_args_required_only_and_types():
    schema = {
        "type": "object",
        "properties": {
            "q": {"type": "string"},
            "limit": {"type": "integer"},
            "flag": {"type": "boolean"},
            "items": {"type": "array"},
            "opt": {"type": "string"},
        },
        "required": ["q", "limit", "flag", "items"],
    }
    args = synthesize_args(schema)
    assert set(args) == {"q", "limit", "flag", "items"}  # only required
    assert args["q"] == "test"
    assert args["limit"] == 1
    assert args["flag"] is True
    assert args["items"] == []


def test_synthesize_args_prefers_default_example_enum():
    schema = {
        "properties": {
            "a": {"type": "string", "default": "D"},
            "b": {"type": "string", "examples": ["E"]},
            "c": {"type": "string", "enum": ["X", "Y"]},
        },
        "required": ["a", "b", "c"],
    }
    assert synthesize_args(schema) == {"a": "D", "b": "E", "c": "X"}


def test_synthesize_args_empty():
    assert synthesize_args(None) == {}
    assert synthesize_args({"type": "object"}) == {}


def test_content_error_signal_detects_and_ignores():
    # credential / missing-dep failures returned as *successful* content
    assert _content_error_signal(_text("Error: unauthorized, invalid API key"))
    assert _content_error_signal(_text("ai-dossier CLI not found. Install it"))
    assert _content_error_signal(_text("Access denied: path /data"))
    assert _content_error_signal(_text("You must set the AIRTABLE_API_KEY environment variable"))
    # legitimate content must NOT trip the gate
    assert _content_error_signal(_text("Here are 5 hotels in Paris with prices")) is None
    assert _content_error_signal(_text('{"records": 42, "ok": true}')) is None


def test_result_json_parses_or_none():
    assert _result_json(_text('{"a": 1}')) == {"a": 1}
    assert _result_json(_text("not json at all")) is None
    assert _result_json({"content": []}) is None


def test_harvest_values_pulls_id_like_scalars():
    payload = '{"repositories": [{"id": 42, "full_name": "octocat/hi", "private": false}, {"id": 7}]}'
    got = _harvest_values(_text(payload), "list_repos")
    pairs = {(d["key"], d["value"]) for d in got}
    assert ("id", 42) in pairs
    assert ("full_name", "octocat/hi") in pairs
    assert all(d["source"] == "list_repos" for d in got)
    # booleans and non-id keys are not harvested
    assert all(d["value"] is not False for d in got)


def test_harvest_values_non_json_is_empty():
    assert _harvest_values(_text("just prose, no structure"), "t") == []


def test_harvest_values_respects_cap():
    big = "{" + ",".join(f'"id_{i}": {i}' for i in range(50)) + "}"
    got = _harvest_values(_text(big), "t", cap=12)
    assert len(got) <= 12
