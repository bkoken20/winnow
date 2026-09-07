"""Does a small-chunk pass plus one whole-document pass beat either alone?

The earlier studies left this open. Small chunks recover far more detail, but the large
settings still found claims the small ones missed -- plausibly document-level synthesis that
only exists when the model sees the whole text. If so, running both and merging should beat
either alone.

A merge is deterministic given both passes' outputs, so once each pass has been run once,
every combination is computed offline at no further model cost.

NOTE ON A PREVIOUS MISTAKE: the earlier study saved summary rows for the 1,000 and 2,000
settings but not their claim texts, which made those runs unusable for any later question.
This script persists every claim text for every setting. Cheap to store, expensive to
regenerate.

Compromises are unchanged from CHUNK_SIZE.md: one extraction model, temperature 0, sameness
inherited from the embedding model at a threshold of 0.93 fixed in advance, and claim
correctness not measured -- this asks how much is found, never whether it is true.
"""

from __future__ import annotations

import json
import os
import sys
import time
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# Paths come from the environment, never hard-coded: these scripts are published, and an
# absolute path from the author's machine makes every "reproduce with..." instruction false
# for everyone else.
#
#   WINNOW_NOTES       folder of markdown used as the document corpus
#   WINNOW_TRANSCRIPT  a plain-text transcript used as the spoken-source sample
def _env_path(name: str, what: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        raise SystemExit(
            f"set {name} to {what}.\n"
            f"  example:  {name}=/path/to/notes python experiments/<script>.py"
        )
    return Path(raw)



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
from winnow.extract import parse_claims_json, split_text
from winnow.llm import OllamaClient
from winnow.packs import find_pack

DUPLICATE_THRESHOLD = 0.93
NUM_CTX = 32768

NOTES = _env_path("WINNOW_NOTES", "a folder of markdown notes")
DOCS = [
    "huggingface-transformers-docs__docs__source__en__llm_tutorial_optimization.md",
    "llama.cpp-docs__docs__backend__SYCL.md",
    "open-webui-docs__docs__troubleshooting__performance.md",
]
VIDEO = _env_path("WINNOW_TRANSCRIPT", "a plain-text transcript file")

DOC_SIZES_TO_RUN = [1_000, 2_000]          # texts were lost; must be regenerated
VIDEO_SIZES_TO_RUN = [1_000, 2_000, 4_000, 40_000]


def extract_at(llm, model, pack, text, chunk_chars):
    started = time.perf_counter()
    claims = []
    for chunk in split_text(text, chunk_chars):
        raw = llm.generate(model, pack.render_extract_prompt(chunk), num_ctx=NUM_CTX, as_json=True)
        for item in parse_claims_json(raw):
            statement = str(item.get("claim") or item.get("statement") or "").strip()
            if statement:
                claims.append(statement)
    return claims, time.perf_counter() - started


def collapse(embedder, claims, cache):
    """Collapse near-duplicates, reusing embeddings across calls."""
    kept, vectors = [], []
    for claim in claims:
        if claim not in cache:
            cache[claim] = embedder.embed(claim)
        vector = cache[claim]
        if any(cosine_similarity(vector, v) >= DUPLICATE_THRESHOLD for v in vectors):
            continue
        kept.append(claim)
        vectors.append(vector)
    return kept, vectors


def covered(vector, pool):
    return any(cosine_similarity(vector, v) >= DUPLICATE_THRESHOLD for v in pool)


def analyse(label, runs, cache, embedder):
    """runs: {size: {"texts": [...], "seconds": float}}"""
    sizes = sorted(runs)
    vectors = {s: [cache[t] for t in runs[s]["texts"]] for s in sizes}

    union = []
    for s in sizes:
        for v in vectors[s]:
            if not covered(v, union):
                union.append(v)

    def coverage(vecs):
        return 100 * sum(1 for v in union if covered(v, vecs)) / len(union)

    print(f"\n{'=' * 74}\n{label}   (union: {len(union)} distinct claims)\n{'=' * 74}")
    print(f"\n{'single pass':>28} {'claims':>7} {'coverage':>9} {'seconds':>9}")
    print("-" * 58)
    singles = {}
    for s in sizes:
        cov = coverage(vectors[s])
        singles[s] = {
            "claims": len(runs[s]["texts"]),
            "coverage": round(cov, 1),
            "seconds": round(runs[s]["seconds"], 1),
        }
        print(f"{s:>22,} chars {len(runs[s]['texts']):>7} {cov:>8.0f}% {runs[s]['seconds']:>9.0f}")

    print(f"\n{'two passes (merged)':>28} {'claims':>7} {'coverage':>9} {'seconds':>9}   vs best single")
    print("-" * 78)
    pairs = {}
    for a, b in combinations(sizes, 2):
        merged_texts = runs[a]["texts"] + runs[b]["texts"]
        kept, kept_vectors = collapse(embedder, merged_texts, cache)
        cov = coverage(kept_vectors)
        seconds = runs[a]["seconds"] + runs[b]["seconds"]
        best_single = max(singles[a]["coverage"], singles[b]["coverage"])
        gain = cov - best_single
        pairs[f"{a}+{b}"] = {
            "claims": len(kept),
            "coverage": round(cov, 1),
            "seconds": round(seconds, 1),
            "gain_over_best_single": round(gain, 1),
        }
        print(
            f"{a:>10,} + {b:<9,} {len(kept):>7} {cov:>8.0f}% {seconds:>9.0f}"
            f"   {gain:+5.0f} pts"
        )
    return {"union_size": len(union), "singles": {str(k): v for k, v in singles.items()},
            "pairs": pairs}


def what_the_big_pass_adds(small_texts, big_texts, cache, embedder, limit=10):
    """Claims the whole-document pass contributed that the small pass missed."""
    small_vectors = [cache[t] for t in small_texts]
    added = [t for t in big_texts if not covered(cache[t], small_vectors)]
    print(f"\nthe whole-document pass adds {len(added)} of its {len(big_texts)} claims:")
    for t in added[:limit]:
        print(f"  + {t[:110]}")
    return added


def main() -> int:
    config = Config.load(HERE.parent / "winnow.json")
    llm = OllamaClient(host=config.ollama_host)
    embedder = build_embedder("ollama", config.embed_model, config.ollama_host)
    pack = find_pack("ai_tooling", Path(config.packs_root))
    cache: dict[str, list[float]] = {}

    # ---- documents -----------------------------------------------------------
    prior = json.loads(_require_prior("chunk_size_results.json", "chunk_size_study.py").read_text(encoding="utf-8"))
    doc_runs = {
        int(size): {"texts": payload["texts"], "seconds": payload["seconds"]}
        for size, payload in prior["results"].items()
    }
    print("reloaded from the first study:", ", ".join(f"{s:,}" for s in sorted(doc_runs)))

    docs = [(n, (NOTES / n).read_text(encoding="utf-8", errors="replace")) for n in DOCS]
    for size in DOC_SIZES_TO_RUN:
        all_claims, seconds = [], 0.0
        for _, text in docs:
            claims, elapsed = extract_at(llm, config.text_model, pack, text, size)
            all_claims.extend(claims)
            seconds += elapsed
        kept, _ = collapse(embedder, all_claims, cache)
        doc_runs[size] = {"texts": kept, "seconds": seconds}
        print(f"  ran {size:>7,}: {len(all_claims)} claims, {len(kept)} unique, {seconds:.0f}s")

    for run in doc_runs.values():
        for t in run["texts"]:
            if t not in cache:
                cache[t] = embedder.embed(t)

    doc_report = analyse("PART A -- written documentation (3 docs, ~150 KB)", doc_runs, cache, embedder)
    doc_added = what_the_big_pass_adds(
        doc_runs[2_000]["texts"], doc_runs[120_000]["texts"], cache, embedder
    )

    # ---- video ---------------------------------------------------------------
    video_text = VIDEO.read_text(encoding="utf-8", errors="replace")
    video_runs = {}
    print(f"\nspoken transcript ({len(video_text) / 1024:.1f} KB)")
    for size in VIDEO_SIZES_TO_RUN:
        claims, seconds = extract_at(llm, config.text_model, pack, video_text, size)
        kept, _ = collapse(embedder, claims, cache)
        video_runs[size] = {"texts": kept, "seconds": seconds}
        print(f"  ran {size:>7,}: {len(claims)} claims, {len(kept)} unique, {seconds:.0f}s")

    for run in video_runs.values():
        for t in run["texts"]:
            if t not in cache:
                cache[t] = embedder.embed(t)

    video_report = analyse("PART B -- spoken transcript (21 KB)", video_runs, cache, embedder)
    video_added = what_the_big_pass_adds(
        video_runs[2_000]["texts"], video_runs[40_000]["texts"], cache, embedder
    )

    (HERE / "two_pass_results.json").write_text(
        json.dumps(
            {
                "model": config.text_model,
                "embed_model": config.embed_model,
                "duplicate_threshold": DUPLICATE_THRESHOLD,
                "documents": doc_report,
                "video": video_report,
                "whole_pass_additions": {
                    "documents": doc_added,
                    "video": video_added,
                },
                # Every claim text, so no future question needs a re-run.
                "texts": {
                    "documents": {str(s): r["texts"] for s, r in doc_runs.items()},
                    "video": {str(s): r["texts"] for s, r in video_runs.items()},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {HERE / 'two_pass_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
