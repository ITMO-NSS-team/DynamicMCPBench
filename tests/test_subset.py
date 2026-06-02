"""E3.7/E3.3: `dmcp subset` tag-axis filtering (incl. --exclude-tag)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from dmcp.cli import app

runner = CliRunner()


def _manifest(tmp_path):
    servers = [
        {
            "server_id": "a",
            "transport": "stdio",
            "dynamism": "live_read",
            "command": "x",
            "tags": ["pkg:npm", "domain:web", "size:small", "verify:full"],
        },
        {
            "server_id": "b",
            "transport": "stdio",
            "dynamism": "static",
            "command": "x",
            "tags": ["pkg:pypi", "domain:dev", "deps:yes", "verify:full"],
        },
        {
            "server_id": "c",
            "transport": "sse",
            "dynamism": "stateful_write",
            "sandbox": True,
            "endpoint": "http://x/sse",
            "tags": ["tier:compose", "pkg:docker", "verify:full"],
        },
    ]
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"manifest_version": "0.1.0", "servers": servers}))
    return m


def _ids(path):
    return {s["server_id"] for s in json.loads(path.read_text())["servers"]}


def test_subset_by_dynamism(tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(app, ["subset", "-m", str(_manifest(tmp_path)), "--dyn", "static", "-o", str(out)])
    assert r.exit_code == 0
    assert _ids(out) == {"b"}


def test_subset_by_pkg(tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(app, ["subset", "-m", str(_manifest(tmp_path)), "--pkg", "docker", "-o", str(out)])
    assert r.exit_code == 0
    assert _ids(out) == {"c"}


def test_subset_exclude_tag(tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(
        app, ["subset", "-m", str(_manifest(tmp_path)), "--exclude-tag", "tier:compose", "-o", str(out)]
    )
    assert r.exit_code == 0
    assert _ids(out) == {"a", "b"}


def test_subset_has_deps(tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(app, ["subset", "-m", str(_manifest(tmp_path)), "--has-deps", "-o", str(out)])
    assert r.exit_code == 0
    assert _ids(out) == {"b"}


def test_subset_predicates_and_together(tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(
        app, ["subset", "-m", str(_manifest(tmp_path)), "--domain", "web", "--pkg", "npm", "-o", str(out)]
    )
    assert r.exit_code == 0
    assert _ids(out) == {"a"}
