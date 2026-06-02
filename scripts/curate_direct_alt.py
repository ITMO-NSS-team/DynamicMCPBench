#!/usr/bin/env python3
"""E6.4: curate manifests/direct_alt.json. Each same-name cross-server group is scored as a
true ALTERNATIVE vs a possible HOMONYM using the members' server domains: members that share
a domain are high-confidence alternatives (auto-reviewed); cross-domain members are low
confidence (reviewed=false → flagged for human κ≥0.7 review). Used by the cross_server_alt
generation strategy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--direct-alt", default="manifests/direct_alt.json")
    ap.add_argument("--manifest", default="manifests/servers.json")
    a = ap.parse_args()

    groups = json.loads((ROOT / a.direct_alt).read_text(encoding="utf-8"))
    domain_of: dict[str, str] = {}
    for e in json.loads((ROOT / a.manifest).read_text(encoding="utf-8"))["servers"]:
        domain_of[e["server_id"]] = next(
            (t.split(":", 1)[1] for t in e.get("tags", []) if t.startswith("domain:")), "?"
        )

    hi = lo = 0
    for grp in groups:
        sids = [m["server_id"] for m in grp.get("members", [])]
        domains = {domain_of.get(s, "?") for s in sids}
        high = len(domains) == 1 and "?" not in domains
        grp["confidence"] = "high" if high else "low"
        grp["reviewed"] = bool(high)  # high → auto-accepted; low → flagged for human κ review
        hi += high
        lo += not high

    (ROOT / a.direct_alt).write_text(json.dumps(groups, indent=2), encoding="utf-8")
    print(
        f"curated {len(groups)} groups: {hi} high-confidence alternatives (reviewed), "
        f"{lo} low (possible homonyms — flagged for human review)"
    )


if __name__ == "__main__":
    main()
