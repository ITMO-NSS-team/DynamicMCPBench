"""Launch-time checks that prevent frontend/backend drift."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = ROOT / "dmcp-studio" / "scripts" / "check_studio_server.py"
spec = importlib.util.spec_from_file_location("check_studio_server", HELPER_PATH)
assert spec and spec.loader
check_studio_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_studio_server)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_check_studio_server_classifies_current_backend(monkeypatch):
    monkeypatch.setattr(
        check_studio_server,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            {"status": "ok", "capabilities": {"advisor_v2": True}},
        ),
    )

    assert check_studio_server.classify(8000) == "current"


def test_check_studio_server_classifies_stale_studio_backend(monkeypatch):
    monkeypatch.setattr(
        check_studio_server,
        "urlopen",
        lambda *_args, **_kwargs: _Response({"status": "ok", "mode_default": "replay"}),
    )

    assert check_studio_server.classify(8000) == "stale"


def test_check_studio_server_classifies_non_studio_service(monkeypatch):
    monkeypatch.setattr(
        check_studio_server,
        "urlopen",
        lambda *_args, **_kwargs: _Response({"status": "different"}),
    )

    assert check_studio_server.classify(8000) == "occupied"


def test_check_studio_server_classifies_refused_connection_as_free(monkeypatch):
    def _raise_refused(*_args: object, **_kwargs: object) -> None:
        raise ConnectionRefusedError()

    monkeypatch.setattr(check_studio_server, "urlopen", _raise_refused)

    assert check_studio_server.classify(8000) == "free"


def test_check_studio_server_classifies_unreachable_service_as_occupied(monkeypatch):
    def _raise_unreachable(*_args: object, **_kwargs: object) -> None:
        raise URLError("timeout")

    monkeypatch.setattr(check_studio_server, "urlopen", _raise_unreachable)

    assert check_studio_server.classify(8000) == "occupied"
