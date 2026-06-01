"""E3 Phase B: arg synthesis + destructive-tool detection (offline)."""

from __future__ import annotations

from dmcp.verify import is_destructive, synthesize_args


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
