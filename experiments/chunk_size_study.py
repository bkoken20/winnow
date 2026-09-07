"""Does chunk size change how much a model actually extracts?

The question arose from a real run: a 47 KB document fits in one 32k-context chunk and
yielded only 6 claims. The suspicion is that a model given a very large span summarises
rather than enumerates.

Counting claims alone cannot answer this. More chunks means more extraction calls, so more
claims appear by construction whether or not they are worth having. This measures three
things instead:

  claims        raw count
  unique        after collapsing near-duplicates (real embeddings, cosine >= 0.93)
  coverage      of the union of everything any setting found, how much did this one find?
  seconds       what it cost

Compromises, stated before the result is read:
  - One extraction model (qwen2.5:14b-instruct) at temperature 0. Another model may differ.
  - Three documents. Enough to avoid a single-document artifact, not enough to generalise
    to all documentation.
  - "Unique" and "coverage" use embedding similarity, so they inherit the embedding
    model's notion of sameness. A threshold of 0.93 was chosen before running.
  - Claim *correctness* is not measured here at all. This measures how much is found, not
    whether it is true.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


from winnow.config import Config
from winnow.embed import build_embedder, cosine_similarity
from winnow.extract import parse_claims_json, split_text
from winnow.llm import OllamaClient
from winnow.packs import find_pack

CHUNK_SIZES = [4_000, 12_000, 30_000, 120_000]  # 120k = current default at num_ctx 32768
DUPLICATE_THRESHOLD = 0.93
NUM_CTX = 32768

# The three largest markdown files in WINNOW_NOTES, whatever they are.
#
# These studies used to name three specific documents from the author's own corpus, which
# made every "reproduce with..." instruction impossible for anyone else -- a forker pointed
# WINNOW_NOTES at their notes and got a traceback about a filename they had never seen.
# Absolute numbers will differ with different documents; the COMPARISON between settings is
# what the studies are about, and that holds on any reasonably substantial corpus.
def _largest_docs(folder: Path, count: int = 3) -> list[str]:
    files = sorted(folder.glob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
    if len(files) < count:
        raise SystemExit(
            f"{folder} holds {len(files)} markdown files; this study needs at least {count}.
"
            f"  Populate it first:  python scripts/fetch_starter_corpus.py --dest {folder}"
        )
    return [f.name for f in files[:count]]


def extract_at(llm, model, pack, text: str, chunk_chars: int) -> tuple[list[str], float]:
    started = time.perf_counter()
    claims: list[str] = []
    for chunk in split_text(text, chunk_chars):
        raw = llm.generate(model, pack.render_extract_prompt(chunk), num_ctx=NUM_CTX, as_json=True)
        for item in parse_claims_json(raw):
            statement = str(item.get("claim") or item.get("statement") or "").strip()
            if statement:
                claims.append(statement)
    return claims, time.perf_counter() - started


def collapse(embedder, claims: list[str]) -> tuple[list[str], list[list[float]]]:
    """Greedy near-duplicate collapse. Returns kept claims and their vectors."""
    kept: list[str] = []
    vectors: list[list[float]] = []
    for claim in claims:
        vector = embedder.embed(claim)
        if any(cosine_similarity(vector, v) >= DUPLICATE_THRESHOLD for v in vectors):
            continue
        kept.append(claim)
        vectors.append(vector)
    return kept, vectors


def covered(vector, pool: list[list[float]]) -> bool:
    return any(cosine_similarity(vector, v) >= DUPLICATE_THRESHOLD for v in pool)


def main() -> int:
    DOCS = _largest_docs(NOTES)
    notes = _env_path("WINNOW_NOTES", "a folder of markdown notes")
    config = Config.load(Path(__file__).resolve().parent.parent / "winnow.json")
    llm = OllamaClient(host=config.ollama_host)
    embedder = build_embedder("ollama", config.embed_model, config.ollama_host)
    pack = find_pack("ai_tooling", Path(config.packs_root))

    docs = [(name, (notes / name).read_text(encoding="utf-8", errors="replace")) for name in DOCS]
    for name, text in docs:
        print(f"document: {name[:60]}  ({len(text) / 1024:.1f} KB)")
    print()

    # Measure one chunk before committing to the grid.
    probe_started = time.perf_counter()
    llm.generate(
        config.text_model,
        pack.render_extract_prompt(docs[0][1][:4000]),
        num_ctx=NUM_CTX,
        as_json=True,
    )
    per_call = time.perf_counter() - probe_started
    calls = sum(
        len(split_text(text, size)) for _, text in docs for size in CHUNK_SIZES
    )
    print(f"measured {per_call:.1f}s for one extraction call; {calls} calls in the grid")
    print(f"projected {per_call * calls / 60:.1f} minutes\n")

    results: dict[int, dict] = {}
    per_doc: dict[str, dict[int, list[str]]] = {name: {} for name, _ in docs}

    for size in CHUNK_SIZES:
        all_claims: list[str] = []
        seconds = 0.0
        for name, text in docs:
            claims, elapsed = extract_at(llm, config.text_model, pack, text, size)
            per_doc[name][size] = claims
            all_claims.extend(claims)
            seconds += elapsed
        unique, vectors = collapse(embedder, all_claims)
        results[size] = {
            "claims": len(all_claims),
            "unique": len(unique),
            "seconds": seconds,
            "vectors": vectors,
            "texts": unique,
        }
        print(
            f"chunk {size:>6,} chars : {len(all_claims):>3} claims, "
            f"{len(unique):>3} unique, {seconds:>6.1f}s"
        )

    # Union of everything anyone found, then how much of it each setting recovered.
    print("\nbuilding the union of all findings ...")
    union_texts: list[str] = []
    union_vectors: list[list[float]] = []
    for size in CHUNK_SIZES:
        for text, vector in zip(results[size]["texts"], results[size]["vectors"]):
            if not covered(vector, union_vectors):
                union_texts.append(text)
                union_vectors.append(vector)

    print(f"union holds {len(union_texts)} distinct claims\n")
    print(f"{'chunk':>8} {'claims':>7} {'unique':>7} {'dup%':>6} {'coverage':>9} {'seconds':>8}")
    print("-" * 52)
    for size in CHUNK_SIZES:
        r = results[size]
        found = sum(1 for v in union_vectors if covered(v, r["vectors"]))
        dup = 100 * (1 - r["unique"] / r["claims"]) if r["claims"] else 0.0
        print(
            f"{size:>8,} {r['claims']:>7} {r['unique']:>7} {dup:>5.0f}% "
            f"{100 * found / len(union_vectors):>8.0f}% {r['seconds']:>8.1f}"
        )

    out = Path(__file__).resolve().parent / "chunk_size_results.json"
    out.write_text(
        json.dumps(
            {
                "chunk_sizes": CHUNK_SIZES,
                "duplicate_threshold": DUPLICATE_THRESHOLD,
                "model": config.text_model,
                "embed_model": config.embed_model,
                "documents": {name: len(text) for name, text in docs},
                "union_size": len(union_texts),
                "results": {
                    str(size): {
                        "claims": results[size]["claims"],
                        "unique": results[size]["unique"],
                        "seconds": round(results[size]["seconds"], 1),
                        "coverage_pct": round(
                            100
                            * sum(1 for v in union_vectors if covered(v, results[size]["vectors"]))
                            / len(union_vectors),
                            1,
                        ),
                        "texts": results[size]["texts"],
                    }
                    for size in CHUNK_SIZES
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
