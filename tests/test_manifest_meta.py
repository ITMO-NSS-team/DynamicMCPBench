"""E3: optional provenance fields (package / tool_count) + clean dump (exclude_none)."""

from __future__ import annotations

import json

from dmcp.manifest import Manifest, ServerEntry


def _entry(**kw) -> dict:
    base = {"server_id": "s", "transport": "stdio", "dynamism": "live_read", "command": "uvx"}
    base.update(kw)
    return base


def test_serverentry_accepts_package_and_tool_count():
    e = ServerEntry.model_validate(
        _entry(
            args=["--from", "pkg==1.0", "pkg"],
            package={"kind": "pypi", "identifier": "pkg", "version": "1.0", "entrypoint": "pkg"},
            tool_count=7,
            tags=["crawled", "pkg:pypi"],
        )
    )
    assert e.package["identifier"] == "pkg"
    assert e.tool_count == 7


def test_dump_excludes_none(tmp_path):
    m = Manifest(
        manifest_version="0.1.0",
        servers=[ServerEntry.model_validate(_entry(args=["x"]))],  # no package/env/endpoint/tool_count
    )
    out = tmp_path / "m.json"
    m.dump(out)
    raw = json.loads(out.read_text())
    entry = raw["servers"][0]
    # null optionals must NOT be serialized
    for absent in ("env", "endpoint", "headers", "package", "tool_count"):
        assert absent not in entry, f"{absent} should be omitted when None"
    # required/non-null fields remain
    assert entry["command"] == "uvx"
    assert entry["dynamism"] == "live_read"
    # round-trips back to a valid manifest
    assert len(Manifest.load(out).servers) == 1


def test_dump_keeps_populated_package(tmp_path):
    m = Manifest(
        manifest_version="0.1.0",
        servers=[
            ServerEntry.model_validate(
                _entry(args=["--from", "p", "p"], package={"kind": "pypi", "identifier": "p"}, tool_count=3)
            )
        ],
    )
    out = tmp_path / "m.json"
    m.dump(out)
    entry = json.loads(out.read_text())["servers"][0]
    assert entry["package"] == {"kind": "pypi", "identifier": "p"}
    assert entry["tool_count"] == 3
