#!/usr/bin/env python3
"""Merge a contributor's valid corpus into the shared HF dataset + rebuild the card.

The script every contributor runs. With their own validator-valid specs + traces it:
  1. uploads their slice to ``parts/<name>/{specs,traces}.jsonl`` (per-contributor — never clobbers anyone),
  2. downloads every ``parts/*``, unions them (specs deduped by ``task_id``, traces by content),
  3. rebuilds the merged top-level ``specs.jsonl`` / ``traces.jsonl`` / ``labels.json`` / ``README.md``
     (combined stats + a per-contributor table) by reusing ``release_hf.build``, and
  4. pushes the merged files.

Idempotent + race-resilient: parts are per-contributor and the merge is a deterministic
union, so two contributors running concurrently converge to the same dataset. A secret
scan refuses to upload anything key-shaped. Needs ``huggingface_hub`` + ``HF_TOKEN``
(write access to the org).

  uv run python scripts/merge_to_hf.py --name <you> \\
      --specs data/<corpus>/specs_valid.jsonl --traces data/<corpus>/traces.jsonl \\
      --manifest manifests/servers.json --repo-id TokenWasteGroup/DynamicMCPBench --push

Dry-run (default, no --push) just reports what your slice contributes.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import release_hf  # noqa: E402  (reuse the dataset builder + secret scan)


def _load(p: str | Path) -> list[dict]:
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def _valid(specs: list[dict]) -> list[dict]:
    return [s for s in specs if (s.get("provenance") or {}).get("validator", {}).get("verdict") == "valid"]


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="contributor id (your slice -> parts/<name>/)")
    ap.add_argument("--specs", required=True, help="your validator-valid specs JSONL")
    ap.add_argument("--traces", required=True, help="your reference traces JSONL")
    ap.add_argument("--manifest", default="manifests/servers.json")
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--license", default="cc-by-4.0")
    ap.add_argument("--direct-alt", default=None)
    ap.add_argument("--push", action="store_true", help="upload (needs huggingface_hub + HF_TOKEN)")
    a = ap.parse_args()

    name = "".join(c for c in a.name if c.isalnum() or c in "-_") or "anon"
    my_specs = _valid(_load(a.specs))
    my_traces = _load(a.traces)
    if not my_specs:
        raise SystemExit(f"no validator-valid specs in {a.specs}")

    # never let key-shaped content leave the machine
    for p in (a.specs, a.traces):
        hits = release_hf._scan_secrets(Path(p))
        if hits:
            raise SystemExit(f"secret-shaped content in {p}: {hits[:3]} — refusing to upload")

    stage = Path(tempfile.mkdtemp(prefix="hfmerge_"))
    _write_jsonl(stage / "my_specs.jsonl", my_specs)
    _write_jsonl(stage / "my_traces.jsonl", my_traces)

    if not a.push:
        print(f"[merge] dry-run: '{name}' contributes {len(my_specs)} valid specs / {len(my_traces)} traces.")
        print("        re-run with --push to upload your part + rebuild the merged dataset.")
        return

    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()  # HF_TOKEN from env / cached login
    repo = a.repo_id
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)

    # 1) upload my part (per-contributor path — no clobber)
    api.upload_file(
        path_or_fileobj=str(stage / "my_specs.jsonl"),
        path_in_repo=f"parts/{name}/specs.jsonl",
        repo_id=repo,
        repo_type="dataset",
    )
    api.upload_file(
        path_or_fileobj=str(stage / "my_traces.jsonl"),
        path_in_repo=f"parts/{name}/traces.jsonl",
        repo_id=repo,
        repo_type="dataset",
    )
    print(f"[merge] uploaded part parts/{name}/ ({len(my_specs)} specs)")

    # 2) download every part + union
    files = api.list_repo_files(repo, repo_type="dataset")
    contributors = sorted({f.split("/")[1] for f in files if f.startswith("parts/") and f.count("/") == 2})
    merged_specs, seen_task, per_contrib = [], set(), {}
    merged_traces, seen_trace = [], set()
    for c in contributors:
        sp = _load(hf_hub_download(repo, f"parts/{c}/specs.jsonl", repo_type="dataset"))
        tr = _load(hf_hub_download(repo, f"parts/{c}/traces.jsonl", repo_type="dataset"))
        added = 0
        for s in sp:
            tid = s.get("task_id")
            if tid and tid in seen_task:
                continue
            seen_task.add(tid)
            merged_specs.append(s)
            added += 1
        for t in tr:
            k = json.dumps(t, sort_keys=True)
            if k in seen_trace:
                continue
            seen_trace.add(k)
            merged_traces.append(t)
        per_contrib[c] = added
    print(
        f"[merge] union: {len(merged_specs)} specs / {len(merged_traces)} traces over "
        f"{len(contributors)} contributors {per_contrib}"
    )

    # 3) rebuild merged dataset (labels + README) via release_hf, then append contributors
    _write_jsonl(stage / "merged_specs.jsonl", merged_specs)
    _write_jsonl(stage / "merged_traces.jsonl", merged_traces)
    out = stage / "release"
    release_hf.build(
        argparse.Namespace(
            specs=str(stage / "merged_specs.jsonl"),
            traces=str(stage / "merged_traces.jsonl"),
            manifest=a.manifest,
            direct_alt=a.direct_alt,
            out=str(out),
            repo_id=repo,
            license=a.license,
            push=False,
        )
    )
    card = (out / "README.md").read_text(encoding="utf-8")
    rows = "\n".join(f"| {c} | {per_contrib[c]} |" for c in contributors)
    card += f"\n\n## Contributors\n\n| contributor | valid specs |\n|---|---|\n{rows}\n"
    (out / "README.md").write_text(card, encoding="utf-8")

    # 4) push merged top-level files
    for fn in ("specs.jsonl", "traces.jsonl", "labels.json", "README.md"):
        api.upload_file(path_or_fileobj=str(out / fn), path_in_repo=fn, repo_id=repo, repo_type="dataset")
    print(
        f"[merge] pushed merged dataset ({len(merged_specs)} specs) + README -> "
        f"https://huggingface.co/datasets/{repo}"
    )


if __name__ == "__main__":
    main()
