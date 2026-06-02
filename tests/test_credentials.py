"""E3.4: credentialed tier — requires_env, env plumbing from os.environ, gating."""

from __future__ import annotations

from dmcp.manifest import Manifest, ServerEntry


def _entry(**kw) -> ServerEntry:
    base = {
        "server_id": "s",
        "transport": "stdio",
        "dynamism": "live_read",
        "command": "npx",
        "args": ["-y", "pkg"],
    }
    base.update(kw)
    return ServerEntry.model_validate(base)


def test_requires_env_defaults_empty_and_settable():
    assert _entry().requires_env == []
    assert _entry(requires_env=["FOO"]).requires_env == ["FOO"]


def test_to_config_plumbs_secret_from_environ(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    e = _entry(requires_env=["FOO"])
    assert e.to_config().env is None  # absent → nothing plumbed (secret never in manifest)
    monkeypatch.setenv("FOO", "s3cret")
    assert e.to_config().env == {"FOO": "s3cret"}


def test_gate_credentials_skips_missing_includes_present(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAR", raising=False)
    m = Manifest(
        manifest_version="0.1.0",
        servers=[
            _entry(server_id="needs_foo", requires_env=["FOO"]),
            _entry(server_id="needs_two", requires_env=["FOO", "BAR"]),
            _entry(server_id="no_creds"),
        ],
    )
    runnable, skipped = m.gate_credentials(load_env=False)
    assert [e.server_id for e in runnable] == ["no_creds"]
    assert skipped == [("needs_foo", ["FOO"]), ("needs_two", ["FOO", "BAR"])]

    monkeypatch.setenv("FOO", "x")
    monkeypatch.setenv("BAR", "y")
    runnable, skipped = m.gate_credentials(load_env=False)
    assert {e.server_id for e in runnable} == {"needs_foo", "needs_two", "no_creds"}
    assert skipped == []


def test_gate_credentials_subset(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    m = Manifest(
        manifest_version="0.1.0",
        servers=[_entry(server_id="a", requires_env=["FOO"]), _entry(server_id="b")],
    )
    runnable, skipped = m.gate_credentials(["a"], load_env=False)
    assert runnable == [] and skipped == [("a", ["FOO"])]
