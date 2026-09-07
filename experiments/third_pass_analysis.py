"""What would a third pass cost, and what would it buy?

Computed entirely from stored outputs -- two_pass_study.py persisted every claim text for
every setting, so all merges are deterministic and need no further extraction. Only
embeddings are recomputed.
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def _require_prior(filename: str, produced_by: str) -> Path:
    """Study outputs are not committed -- they embed verbatim source text, including
    third-party material. Scripts that build on an earlier study therefore have to say
    plainly what to run first, rather than dying on a missing file."""
    path = HERE / filename
    if not path.exists():
        raise SystemExit(
            f"{filename} not found.\n"
            f"  This study builds on an earlier one. Run it first:\n"
            f"      python experiments/{produced_by}\n"
            f"  Study outputs are deliberately not committed (they contain verbatim source\n"
            f"  text); each script regenerates its own."
        )
    return path


from winnow.config import Config
from winnow.embed import build_embedder, cosine_similarity

THRESHOLD = 0.93

# Measured seconds per setting, from the studies.
DOC_SECONDS = {1_000: 1060, 2_000: 836, 4_000: 609, 12_000: 249, 30_000: 206, 120_000: 135}
VID_SECONDS = {1_000: 104, 2_000: 101, 4_000: 67, 40_000: 30}


def covered(vector, pool):
    return any(cosine_similarity(vector, v) >= THRESHOLD for v in pool)


def collapse(vectors_by_text, texts):
    kept = []
    for t in texts:
        v = vectors_by_text[t]
        if not covered(v, kept):
            kept.append(v)
    return kept


def analyse(label, texts_by_size, seconds_by_size, embedder):
    sizes = sorted(texts_by_size, key=int)
    cache = {}
    for size in sizes:
        for t in texts_by_size[size]:
            if t not in cache:
                cache[t] = embedder.embed(t)

    union = []
    for size in sizes:
        for t in texts_by_size[size]:
            if not covered(cache[t], union):
                union.append(cache[t])

    def score(size_group):
        texts = [t for s in size_group for t in texts_by_size[s]]
        kept = collapse(cache, texts)
        cov = 100 * sum(1 for v in union if covered(v, kept)) / len(union)
        secs = sum(seconds_by_size[int(s)] for s in size_group)
        return len(kept), cov, secs

    print(f"\n{'=' * 78}\n{label}   (union: {len(union)} claims)\n{'=' * 78}")
    print(f"{'passes':<28} {'claims':>7} {'coverage':>9} {'minutes':>9} {'gain':>7}")
    print("-" * 66)

    small = [s for s in sizes if int(s) <= 4_000]
    rows = {}

    for group in [(s,) for s in small]:
        n, cov, secs = score(group)
        rows[group] = (n, cov, secs)
        print(f"{'+'.join(f'{int(s):,}' for s in group):<28} {n:>7} {cov:>8.0f}% {secs / 60:>8.1f}")

    print()
    two = {}
    for group in combinations(small, 2):
        n, cov, secs = score(group)
        two[group] = cov
        rows[group] = (n, cov, secs)
        best = max(rows[(g,)][1] for g in group)
        print(
            f"{'+'.join(f'{int(s):,}' for s in group):<28} {n:>7} {cov:>8.0f}% {secs / 60:>8.1f}"
            f" {cov - best:>+6.0f}"
        )

    print()
    for group in combinations(small, 3):
        n, cov, secs = score(group)
        best_pair = max(two[p] for p in combinations(group, 2))
        print(
            f"{'+'.join(f'{int(s):,}' for s in group):<28} {n:>7} {cov:>8.0f}% {secs / 60:>8.1f}"
            f" {cov - best_pair:>+6.0f}"
        )
    print("\n(gain column: two-pass vs its best single; three-pass vs its best pair)")


def main() -> int:
    config = Config.load(HERE.parent / "winnow.json")
    embedder = build_embedder("ollama", config.embed_model, config.ollama_host)
    data = json.loads(_require_prior("two_pass_results.json", "two_pass_study.py").read_text(encoding="utf-8"))

    docs = {int(k): v for k, v in data["texts"]["documents"].items()}
    video = {int(k): v for k, v in data["texts"]["video"].items()}

    analyse("DOCUMENTATION (3 docs, ~150 KB)", docs, DOC_SECONDS, embedder)
    analyse("SPOKEN TRANSCRIPT (21 KB)", video, VID_SECONDS, embedder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
