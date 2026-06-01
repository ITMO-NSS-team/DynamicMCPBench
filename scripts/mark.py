#!/usr/bin/env python3
"""Set a plan step's status on main, atomically (see docs/AUTONOMY.md).

Usage:
    scripts/mark.py <step-id> <status> [note...]

<status> is written verbatim, so it may carry a PR ref, e.g.
    scripts/mark.py E1.1 "in_review (#12)"
    scripts/mark.py E1.1 done
    scripts/mark.py E1.1 blocked "upstream server 502s; needs retry"

Same optimistic-lock loop as claim.py: fetch + hard-reset to origin/main, edit
the step's `- status:` line (and a `- note:` line for blocked), commit, push;
retry on rejection. Run on a clean `main`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PLAN = "docs/PLAN.md"
RETRIES = 8
HEADER = re.compile(r"^### +(\S+)\b")


def git(*args, check=True):
    r = subprocess.run(["git", *args], text=True, capture_output=True)
    if check and r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"git {' '.join(args)} failed")
    return r


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    step_id, status = sys.argv[1], sys.argv[2]
    note = " ".join(sys.argv[3:]).strip()

    git("checkout", "main", check=False)
    for _ in range(RETRIES):
        git("fetch", "origin", "main")
        git("reset", "--hard", "origin/main")
        lines = Path(PLAN).read_text(encoding="utf-8").splitlines()

        # locate the target block's line range
        start = None
        for i, line in enumerate(lines):
            m = HEADER.match(line)
            if m and m.group(1) == step_id:
                start = i
                break
        if start is None:
            print(f"step {step_id!r} not found in {PLAN}")
            return 3
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if HEADER.match(lines[i]):
                end = i
                break

        status_idx = note_idx = None
        for i in range(start, end):
            if re.match(r"^- status:", lines[i]):
                status_idx = i
            elif re.match(r"^- note:", lines[i]):
                note_idx = i
        if status_idx is None:
            print(f"step {step_id!r} has no `- status:` line")
            return 3
        lines[status_idx] = f"- status: {status}"
        if note:
            if note_idx is not None:
                lines[note_idx] = f"- note: {note}"
            else:
                lines.insert(status_idx + 1, f"- note: {note}")

        Path(PLAN).write_text("\n".join(lines) + "\n", encoding="utf-8")
        git("add", PLAN)
        git("commit", "-m", f"chore(plan): mark {step_id} {status}")
        if git("push", "origin", "main", check=False).returncode == 0:
            print(f"MARKED {step_id} -> {status}")
            return 0
        sys.stderr.write("push rejected; re-syncing\n")
    print("retries exhausted")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
