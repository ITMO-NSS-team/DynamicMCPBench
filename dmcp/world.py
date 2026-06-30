"""World storage — snapshot and restore the compose stack's persistent state.

Minimal v0: a *seed* storage layer. `capture` tars every docker named volume of
the compose project into `worlds/<id>/`; `restore` wipes and untars them back.
That lets live (non-replay) eval start each candidate from byte-identical state
when the operator brackets a run with capture-once / restore-each.

Mechanism is uniform and schema-agnostic: a throwaway `alpine` helper container
mounts each volume and tars it — no per-store tooling, no knowledge of mongo /
postgres internals. Reset volumes while the services are idle for a consistent
snapshot.

Scope of v0: capture / restore / list over docker volumes, driven by hand or by
a future eval hook. Out of scope: per-store logical dumps, manifest/TaskSpec
schema changes, automatic eval integration, the --replay path (untouched, stays
deterministic and offline).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

WORLD_SCHEMA_VERSION = "0.1.0"

RunResult = subprocess.CompletedProcess
Runner = Callable[..., RunResult]


def default_runner(argv: list[str], *, input: bytes | None = None) -> RunResult:
    """Run a command, capturing output and raising on non-zero exit."""
    return subprocess.run(argv, input=input, capture_output=True, check=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class VolumeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared: str  # volume name as declared in the compose file
    volume: str  # real docker volume name (project-prefixed)
    artifact: str  # tar filename within the fixture dir
    sha256: str


class WorldFixture(BaseModel):
    """On-disk record of one captured world, saved as worlds/<id>/manifest.json
    beside the per-volume tar artifacts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = WORLD_SCHEMA_VERSION
    fixture_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    project: str
    volumes: list[VolumeSnapshot]

    def save(self, dir: Path) -> None:
        dir.mkdir(parents=True, exist_ok=True)
        (dir / "manifest.json").write_text(
            json.dumps(self.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, dir: Path) -> WorldFixture:
        return cls.model_validate_json((dir / "manifest.json").read_text(encoding="utf-8"))


class WorldStore:
    """Capture / restore / list world fixtures over a compose project's volumes."""

    def __init__(
        self,
        compose_file: str = "docker-compose-mcp.yaml",
        worlds_dir: Path = Path("worlds"),
        runner: Runner = default_runner,
    ):
        self.compose_file = compose_file
        self.worlds_dir = Path(worlds_dir)
        self.run = runner

    def project_and_volumes(self) -> tuple[str, list[str]]:
        """Resolve the compose project name and its declared volume names.

        `docker compose config` only renders top-level volumes that an *active*
        service references. A profile-gated compose file (every service behind
        `profiles:`) renders zero services — and therefore zero volumes — unless
        a profile is active. When `config` yields none, fall back to the live
        project's actual volumes (labelled by compose) so capture reflects what
        is really deployed instead of an empty profile-filtered render.
        """
        res = self.run(["docker", "compose", "-f", self.compose_file, "config", "--format", "json"])
        cfg = json.loads(res.stdout.decode())
        project = cfg.get("name") or Path(self.compose_file).parent.name
        declared = sorted((cfg.get("volumes") or {}).keys())
        if not declared:
            declared = self._live_project_volumes(project)
        return project, declared

    def _live_project_volumes(self, project: str) -> list[str]:
        """Declared volume names of the running compose project, via docker labels.

        Names are returned with the `<project>_` prefix stripped so they match
        the `config`-derived form; `capture` re-adds the prefix for the real
        docker volume name.
        """
        res = self.run(
            [
                "docker",
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Name}}",
            ]
        )
        prefix = f"{project}_"
        names = (line for line in res.stdout.decode().splitlines() if line.strip())
        return sorted(n.removeprefix(prefix) for n in names)

    def capture(self, fixture_id: str, volumes: list[str] | None = None) -> WorldFixture:
        project, declared_all = self.project_and_volumes()
        declared = volumes if volumes else declared_all
        if not declared:
            raise RuntimeError(
                f"no volumes to capture for project {project!r}: compose `config` rendered "
                "none (profile-gated stack with no active profile?) and the live project has "
                "no labelled volumes. Bring the stack up, activate a profile, or pass volumes "
                "explicitly. Refusing to write an empty fixture (a silent no-op on restore)."
            )
        fdir = (self.worlds_dir / fixture_id).resolve()
        fdir.mkdir(parents=True, exist_ok=True)
        snaps: list[VolumeSnapshot] = []
        for name in declared:
            real = f"{project}_{name}"
            artifact = fdir / f"{name}.tar"
            self.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{real}:/data:ro",
                    "-v",
                    f"{fdir}:/backup",
                    "alpine",
                    "tar",
                    "-C",
                    "/data",
                    "-cf",
                    f"/backup/{artifact.name}",
                    ".",
                ]
            )
            snaps.append(
                VolumeSnapshot(
                    declared=name, volume=real, artifact=artifact.name, sha256=sha256_file(artifact)
                )
            )
        fx = WorldFixture(fixture_id=fixture_id, project=project, volumes=snaps)
        fx.save(fdir)
        return fx

    def restore(self, fixture_id: str) -> None:
        fdir = (self.worlds_dir / fixture_id).resolve()
        fx = WorldFixture.load(fdir)
        for snap in fx.volumes:
            artifact = fdir / snap.artifact
            actual = sha256_file(artifact)
            if actual != snap.sha256:
                raise ValueError(f"{snap.declared}: sha256 mismatch ({actual} != {snap.sha256})")
            self.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{snap.volume}:/data",
                    "-v",
                    f"{fdir}:/backup",
                    "alpine",
                    "sh",
                    "-c",
                    f"find /data -mindepth 1 -delete && tar -C /data -xf /backup/{snap.artifact}",
                ]
            )

    def list(self) -> list[str]:
        if not self.worlds_dir.exists():
            return []
        return sorted(p.name for p in self.worlds_dir.iterdir() if (p / "manifest.json").exists())
