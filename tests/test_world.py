"""Unit tests for dmcp.world — capture/restore/list over compose volumes.

A FakeRunner stands in for docker: it records every argv and, for the
`tar` capture call, writes the artifact so sha256 + the on-disk record are real.
No Docker daemon is required.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from dmcp.world import WorldFixture, WorldStore, sha256_file

_CONFIG_JSON = json.dumps(
    {"name": "dynamicmcpbench", "volumes": {"mongo-data": {}, "postgres-data": {}}}
).encode()


class FakeRunner:
    """Records argv; fakes `docker compose config` and writes tar artifacts."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, *, input=None):
        self.calls.append(list(argv))
        if "config" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=_CONFIG_JSON, stderr=b"")
        # emulate `docker run ... tar -cf /backup/<name> .` by writing the host file
        if "tar" in argv and "-cf" in argv:
            # the host fixture dir is the `-v <hostdir>:/backup` mount
            hostdir = next(a.rsplit(":", 1)[0] for a in argv if a.endswith(":/backup"))
            name = argv[argv.index("-cf") + 1].removeprefix("/backup/")
            (__import__("pathlib").Path(hostdir) / name).write_bytes(b"TARBYTES-" + name.encode())
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")


def test_project_and_volumes_parses_config():
    store = WorldStore(runner=FakeRunner())
    project, vols = store.project_and_volumes()
    assert project == "dynamicmcpbench"
    assert vols == ["mongo-data", "postgres-data"]


def test_capture_writes_fixture_and_tars(tmp_path):
    run = FakeRunner()
    store = WorldStore(worlds_dir=tmp_path, runner=run)
    fx = store.capture("seed-001")

    assert fx.project == "dynamicmcpbench"
    assert {v.declared for v in fx.volumes} == {"mongo-data", "postgres-data"}
    # real volume names are project-prefixed
    assert {v.volume for v in fx.volumes} == {"dynamicmcpbench_mongo-data", "dynamicmcpbench_postgres-data"}
    # manifest + tar artifacts exist on disk
    fdir = tmp_path / "seed-001"
    assert (fdir / "manifest.json").exists()
    assert (fdir / "mongo-data.tar").exists()
    # a docker run with read-only mount was issued
    assert any("docker" in c and "run" in c and any(a.endswith(":ro") for a in c) for c in run.calls)


def test_capture_can_subset_volumes(tmp_path):
    store = WorldStore(worlds_dir=tmp_path, runner=FakeRunner())
    fx = store.capture("seed-002", volumes=["mongo-data"])
    assert [v.declared for v in fx.volumes] == ["mongo-data"]


def test_restore_verifies_sha256_then_runs(tmp_path):
    run = FakeRunner()
    store = WorldStore(worlds_dir=tmp_path, runner=run)
    store.capture("seed-001")
    run.calls.clear()
    store.restore("seed-001")
    # restore issues a wipe+untar docker run per volume
    untar = [c for c in run.calls if "sh" in c and any("tar -C /data -xf" in a for a in c)]
    assert len(untar) == 2


def test_restore_aborts_on_tampered_artifact(tmp_path):
    store = WorldStore(worlds_dir=tmp_path, runner=FakeRunner())
    store.capture("seed-001")
    (tmp_path / "seed-001" / "mongo-data.tar").write_bytes(b"TAMPERED")
    with pytest.raises(ValueError, match="sha256"):
        store.restore("seed-001")


def test_list_returns_fixture_ids(tmp_path):
    store = WorldStore(worlds_dir=tmp_path, runner=FakeRunner())
    store.capture("seed-001")
    store.capture("seed-002", volumes=["mongo-data"])
    assert store.list() == ["seed-001", "seed-002"]


def test_fixture_roundtrip(tmp_path):
    store = WorldStore(worlds_dir=tmp_path, runner=FakeRunner())
    store.capture("seed-001")
    loaded = WorldFixture.load(tmp_path / "seed-001")
    assert loaded.fixture_id == "seed-001"
    assert loaded.schema_version == "0.1.0"


def test_sha256_file(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"hello")
    assert sha256_file(p) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


_EMPTY_CONFIG_JSON = json.dumps({"name": "fedotmas", "volumes": {}}).encode()


class ProfileGatedRunner(FakeRunner):
    """`docker compose config` renders no volumes (profile-gated stack); the live
    project still has labelled volumes that `docker volume ls` reports."""

    def __init__(self, live_volumes: list[str] | None = None):
        super().__init__()
        self.live_volumes = (
            live_volumes if live_volumes is not None else ["fedotmas_mongo-data", "fedotmas_postgres-data"]
        )

    def __call__(self, argv, *, input=None):
        if "config" in argv:
            self.calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout=_EMPTY_CONFIG_JSON, stderr=b"")
        if "volume" in argv and "ls" in argv:
            self.calls.append(list(argv))
            out = ("\n".join(self.live_volumes) + "\n").encode()
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr=b"")
        return super().__call__(argv, input=input)


def test_project_and_volumes_falls_back_to_live_volumes_when_config_empty():
    run = ProfileGatedRunner()
    store = WorldStore(runner=run)
    project, vols = store.project_and_volumes()
    assert project == "fedotmas"
    # prefix stripped so it matches the config-derived declared form
    assert vols == ["mongo-data", "postgres-data"]
    # the fallback queried docker by compose-project label
    assert any("volume" in c and "ls" in c for c in run.calls)


def test_capture_uses_live_fallback_and_prefixes_real_names(tmp_path):
    store = WorldStore(worlds_dir=tmp_path, runner=ProfileGatedRunner())
    fx = store.capture("seed-pg")
    assert {v.declared for v in fx.volumes} == {"mongo-data", "postgres-data"}
    assert {v.volume for v in fx.volumes} == {"fedotmas_mongo-data", "fedotmas_postgres-data"}


def test_capture_raises_when_no_volumes_anywhere(tmp_path):
    store = WorldStore(worlds_dir=tmp_path, runner=ProfileGatedRunner(live_volumes=[]))
    with pytest.raises(RuntimeError, match="no volumes to capture"):
        store.capture("seed-empty")
