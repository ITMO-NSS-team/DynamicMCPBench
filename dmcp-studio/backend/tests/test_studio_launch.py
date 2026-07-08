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

LAUNCHER_PATH = ROOT / "dmcp-studio" / "scripts" / "run_demo.py"
launcher_spec = importlib.util.spec_from_file_location("run_demo", LAUNCHER_PATH)
assert launcher_spec and launcher_spec.loader
run_demo = importlib.util.module_from_spec(launcher_spec)
launcher_spec.loader.exec_module(run_demo)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_check_studio_server_classifies_current_backend(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: True)
    monkeypatch.setattr(
        check_studio_server,
        "urlopen",
        lambda *_args, **_kwargs: _Response(
            {"status": "ok", "capabilities": {"advisor_v2": True}},
        ),
    )

    assert check_studio_server.classify(8000) == "current"


def test_check_studio_server_classifies_stale_studio_backend(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: True)
    monkeypatch.setattr(
        check_studio_server,
        "urlopen",
        lambda *_args, **_kwargs: _Response({"status": "ok", "mode_default": "replay"}),
    )

    assert check_studio_server.classify(8000) == "stale"


def test_check_studio_server_classifies_non_studio_service(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: True)
    monkeypatch.setattr(
        check_studio_server,
        "urlopen",
        lambda *_args, **_kwargs: _Response({"status": "different"}),
    )

    assert check_studio_server.classify(8000) == "occupied"


def test_check_studio_server_classifies_refused_connection_as_free(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: True)

    def _raise_refused(*_args: object, **_kwargs: object) -> None:
        raise ConnectionRefusedError()

    monkeypatch.setattr(check_studio_server, "urlopen", _raise_refused)

    assert check_studio_server.classify(8000) == "free"


def test_check_studio_server_classifies_wrapped_refused_connection_as_free(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: True)

    def _raise_refused(*_args: object, **_kwargs: object) -> None:
        raise URLError(ConnectionRefusedError())

    monkeypatch.setattr(check_studio_server, "urlopen", _raise_refused)

    assert check_studio_server.classify(8000) == "free"


def test_check_studio_server_classifies_unreachable_service_as_occupied(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: True)

    def _raise_unreachable(*_args: object, **_kwargs: object) -> None:
        raise URLError("timeout")

    monkeypatch.setattr(check_studio_server, "urlopen", _raise_unreachable)

    assert check_studio_server.classify(8000) == "occupied"


def test_check_studio_server_classifies_closed_tcp_port_as_free(monkeypatch):
    monkeypatch.setattr(check_studio_server, "_tcp_connects", lambda _port: False)

    assert check_studio_server.classify(8000) == "free"


def test_launcher_sets_windows_safe_environment(monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)

    env = run_demo.studio_env()

    assert env["PYTHONUTF8"] == "1"
    assert env["UV_CACHE_DIR"] == str(ROOT / ".uv-cache")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(ROOT / ".uv-python")
    assert str(ROOT) in env["PYTHONPATH"].split(":") or str(ROOT) in env["PYTHONPATH"].split(";")


def test_launcher_exits_without_rebuild_when_current_server_is_running(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(run_demo, "classify", lambda _port: "current")
    monkeypatch.setattr(run_demo, "build_frontend", lambda *_args, **_kwargs: calls.append("frontend"))
    monkeypatch.setattr(run_demo, "ensure_fixtures", lambda *_args, **_kwargs: calls.append("fixtures"))
    monkeypatch.setattr(run_demo, "serve", lambda *_args, **_kwargs: calls.append("serve") or 0)

    assert run_demo.main(["--port", "8123"]) == 0
    assert calls == []


def test_launcher_refuses_stale_server_before_rebuild(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(run_demo, "classify", lambda _port: "stale")
    monkeypatch.setattr(run_demo, "build_frontend", lambda *_args, **_kwargs: calls.append("frontend"))

    assert run_demo.main(["--port", "8123"]) == 1
    assert calls == []


def test_launcher_refuses_occupied_port_before_rebuild(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(run_demo, "classify", lambda _port: "occupied")
    monkeypatch.setattr(run_demo, "build_frontend", lambda *_args, **_kwargs: calls.append("frontend"))

    assert run_demo.main(["--port", "8123"]) == 1
    assert calls == []


def test_launcher_starts_server_after_prepare_steps(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(run_demo, "classify", lambda _port: "free")
    monkeypatch.setattr(run_demo, "build_frontend", lambda *_args, **_kwargs: calls.append("frontend"))
    monkeypatch.setattr(run_demo, "ensure_fixtures", lambda *_args, **_kwargs: calls.append("fixtures"))
    monkeypatch.setattr(run_demo, "serve", lambda _port, _env: calls.append("serve") or 0)

    assert run_demo.main(["--port", "8123"]) == 0
    assert calls == ["frontend", "fixtures", "serve"]
