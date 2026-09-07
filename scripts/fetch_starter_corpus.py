#!/usr/bin/env python3
"""Fetch a pack's starter corpus into a notes folder.

Winnow ships the *recipe*, not the content: this script clones a handful of public,
permissively-licensed documentation repositories and copies their markdown into your notes
folder, where `winnow index` can turn it into a corpus. Nothing third-party is bundled in
this repository, so nobody inherits anyone else's licensing.

    python scripts/fetch_starter_corpus.py --pack ai_tooling --dest /path/to/notes

Requires git on PATH. Shallow clones only. Existing files are left alone.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdx"}


def load_sources(pack: str) -> list[dict]:
    manifest = REPO_ROOT / "packs" / pack / "pack.json"
    if not manifest.exists():
        sys.exit(f"no such pack: {pack}")
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    filename = meta.get("starter_sources")
    if not filename:
        sys.exit(f"pack {pack} declares no starter sources")
    return json.loads((manifest.parent / filename).read_text(encoding="utf-8"))


def have_git() -> bool:
    return shutil.which("git") is not None


def copy_markdown(src_root: Path, wanted: list[str], dest: Path, prefix: str) -> int:
    copied = 0
    for rel in wanted:
        origin = src_root / rel
        if origin.is_file() and origin.suffix.lower() in MARKDOWN_SUFFIXES:
            files = [origin]
        elif origin.is_dir():
            files = [p for p in origin.rglob("*") if p.suffix.lower() in MARKDOWN_SUFFIXES]
        else:
            print(f"    (missing: {rel})")
            continue
        for path in files:
            relative = path.relative_to(src_root)
            flat = f"{prefix}__{str(relative).replace('/', '__').replace(chr(92), '__')}"
            target = dest / flat
            if target.exists():
                continue
            target.write_text(
                path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
            )
            copied += 1
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default="ai_tooling")
    parser.add_argument("--dest", required=True, help="notes folder to populate")
    parser.add_argument("--dry-run", action="store_true", help="list sources and stop")
    args = parser.parse_args()

    sources = load_sources(args.pack)
    dest = Path(args.dest)

    print(f"pack '{args.pack}' declares {len(sources)} starter sources:\n")
    for s in sources:
        print(f"  {s['name']:<32} {s['license']:<14} {s['url']}")
        print(f"  {'':<32} {s['why']}")
    print()

    if args.dry_run:
        print("dry run; nothing fetched")
        return 0
    if not have_git():
        sys.exit("git not found on PATH")

    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for source in sources:
        print(f"fetching {source['name']} ...")
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--filter=blob:none", source["url"], tmp],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"    FAILED: {result.stderr.strip().splitlines()[-1:]}")
                continue
            copied = copy_markdown(Path(tmp), source["paths"], dest, source["name"])
            total += copied
            print(f"    {copied} markdown files")

    print(f"\n{total} files written to {dest}")
    print(f"Next:  winnow index {dest}")
    print("\nThese files keep their original licences; they are yours locally, not part of Winnow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
