"""_extract_validator_json must tolerate the ways LLMs wrap verdict JSON."""

from __future__ import annotations

from dmcp.cli import _extract_validator_json


def test_plain_json():
    assert _extract_validator_json('{"verdict": "valid", "reason": "ok"}') == {
        "verdict": "valid",
        "reason": "ok",
    }


def test_json_code_fence():
    raw = '```json\n{"verdict": "valid", "reason": "well formed"}\n```'
    assert _extract_validator_json(raw)["verdict"] == "valid"


def test_bare_fence():
    raw = '```\n{"verdict": "invalid", "reason": "x"}\n```'
    assert _extract_validator_json(raw)["verdict"] == "invalid"


def test_prose_then_json():
    raw = 'Here is my assessment:\n{"verdict": "valid", "reason": "good"} hope that helps'
    assert _extract_validator_json(raw)["verdict"] == "valid"


def test_garbage_returns_none():
    assert _extract_validator_json("totally not json") is None
    assert _extract_validator_json("") is None


def test_non_dict_returns_none():
    assert _extract_validator_json("[1, 2, 3]") is None
