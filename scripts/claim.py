#!/usr/bin/env python3
"""Atomically claim the next eligible plan step (see docs/AUTONOMY.md).

Optimistic lock with git as the arbiter: edit docs/PLAN.md to mark the first
eligible `todo` step as `claimed`, commit, and push to main. If the push is
rejected (another agent claimed concurrently and pushed first), hard-reset to
origin/main — discarding our local claim — and re-pick. Whoever's push lands
first owns the step; everyone else re-picks the next one.

Run this only on a clean `main`. Prints `CLAIMED <id>` then the step block on
success. Exit codes: 0 claimed, 3 nothing eligible, 4 retries exhausted.
"""

from __future__ import annotations

import datetime
import re
import socket
import subprocess
import sys
from pathlib import Path

PLAN = "docs/PLAN.md"
RETRIES = 8
HEADER = re.compile(r"^### +(\S+)\b")
FIELD = re.compile(r"^- (status|owner|claimed_at|deps|source|done-when):\s*(.*)$")


def git(*args, check=True):
    r = subprocess.run(["git", *args], text=True, capture_output=True)
    if check and r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"git {' '.join(args)} failed")
    return r


def agent_id() -> str:
    name = subprocess.run(
        ["git", "config", "user.name"], text=True, capture_output=True
    ).stdout.strip() or "unknown"
    name = re.sub(r"[^A-Za-z0-9_-]", "-", name)
    return f"{name}@{socket.gethostname()}"


def parse(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    cur: dict | None = None
    for i, line in enumerate(lines):
        m = HEADER.match(line)
        if m:
            cur = {"id": m.group(1), "fields": {}, "start": i}
            blocks.append(cur)
        elif cur is not None:
            fm = FIELD.match(line)
            if fm:
                cur["fields"][fm.group(1)] = (i, fm.group(2).strip())
    return blocks


def status_of(b: dict) -> str | None:
    f = b["fields"].get("status")
    return f[1] if f else None


def deps_of(b: dict) -> list[str]:
    f = b["fields"].get("deps")
    if not f:
        return []
    return [d for d in re.split(r"[,\s]+", f[1]) if d and d not in ("—", "-")]


def pick(blocks: list[dict]) -> dict | None:
    done = {b["id"] for b in blocks if status_of(b) == "done"}
    for b in blocks:
        if status_of(b) == "todo" and all(d in done for d in deps_of(b)):
            return b
    return None


def main() -> int:
    aid = agent_id()
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    git("checkout", "main", check=False)
    for _ in range(RETRIES):
        git("fetch", "origin", "main")
        git("reset", "--hard", "origin/main")
        lines = Path(PLAN).read_text(encoding="utf-8").splitlines()
        blocks = parse(lines)
        b = pick(blocks)
        if b is None:
            print("NONE — no eligible todo step (all done, claimed, or blocked by deps)")
            return 3
        for name, val in (("status", "claimed"), ("owner", aid), ("claimed_at", ts)):
            if name in b["fields"]:
                idx, _ = b["fields"][name]
                lines[idx] = f"- {name}: {val}"
        Path(PLAN).write_text("\n".join(lines) + "\n", encoding="utf-8")
        git("add", PLAN)
        git("commit", "-m", f"chore(plan): claim {b['id']}")
        if git("push", "origin", "main", check=False).returncode == 0:
            print(f"CLAIMED {b['id']}")
            start = b["start"]
            end = len(lines)
            for nb in blocks:
                if nb["start"] > start:
                    end = nb["start"]
                    break
            print("\n".join(lines[start:end]).strip())
            return 0
        sys.stderr.write("push rejected — another agent won the race; re-syncing\n")
    print("retries exhausted")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
