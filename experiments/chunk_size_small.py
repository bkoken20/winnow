"""Part two: does coverage keep climbing below 4,000 characters?

The first study (chunk_size_study.py) measured 4k / 12k / 30k / 120k and found coverage
still rising at the smallest size tested. 4,000 was adopted as "best of those measured",
explicitly not as "optimal". This closes that gap.

Two independent parts, kept apart on purpose:

PART A -- the same three documents as the first study, at 1,000 and 2,000 characters. Prior
results are reloaded from chunk_size_results.json rather than re-run: same documents, same
model, same temperature, same embedder, so the settings are directly comparable and the
union is simply recomputed over the larger set of settings.

PART B -- a spoken transcript, as an independent check. Adding it to Part A would change the
union and invalidate the published coverage figures, so it gets its own union and its own
table. It matters because speech is far less information-dense than written documentation,
and a finding that only holds for dense reference material would be a weaker finding than it
looks.

Compromises are those of the first study, unchanged: one extraction model, temperature 0,
"sameness" from the embedding model at a threshold of 0.93 fixed in advance, and claim
correctness not measured.
"""

from __future__ import annotations

import json
import os
import sys
import time
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

NEW_SIZES = [1_000, 2_000]
VIDEO_SIZES = [1_000, 2_000, 4_000, 40_000]  # 40k = the whole transcript in one call
DUPLICATE_THRESHOLD = 0.93
NUM_CTX = 32768

NOTES = _env_path("WINNOW_NOTES", "a folder of markdown notes")
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
            f"{folder} holds {len(files)} markdown files; "
            f"this study needs at least {count}.\n"
            f"  Populate it first:  "
            f"python scripts/fetch_starter_corpus.py --dest {folder}"
        )
    return [f.name for f in files[:count]]
VIDEO = _env_path("WINNOW_TRANSCRIPT", "a plain-text transcript file")


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


def collapse(embedder, claims):
    kept, vectors = [], []
    for claim in claims:
        vector = embedder.embed(claim)
        if any(cosine_similarity(vector, v) >= DUPLICATE_THRESHOLD for v in vectors):
            continue
        kept.append(claim)
        vectors.append(vector)
    return kept, vectors


def covered(vector, pool):
    return any(cosine_similarity(vector, v) >= DUPLICATE_THRESHOLD for v in pool)


def report(title, results, sizes, embedder):
    """Build the union across all settings, then score each setting against it."""
    union_vectors = []
    for size in sizes:
        for vector in results[size]["vectors"]:
            if not covered(vector, union_vectors):
                union_vectors.append(vector)

    print(f"\n{title}")
    print(f"union holds {len(union_vectors)} distinct claims\n")
    print(f"{'chunk':>8} {'claims':>7} {'unique':>7} {'dup%':>6} {'coverage':>9} {'seconds':>8}")
    print("-" * 52)
    rows = {}
    for size in sizes:
        r = results[size]
        found = sum(1 for v in union_vectors if covered(v, r["vectors"]))
        pct = 100 * found / len(union_vectors) if union_vectors else 0.0
        dup = 100 * (1 - r["unique"] / r["claims"]) if r["claims"] else 0.0
        rows[size] = {
            "claims": r["claims"],
            "unique": r["unique"],
            "dup_pct": round(dup, 1),
            "coverage_pct": round(pct, 1),
            "seconds": round(r["seconds"], 1),
        }
        print(
            f"{size:>8,} {r['claims']:>7} {r['unique']:>7} {dup:>5.0f}% {pct:>8.0f}% "
            f"{r['seconds']:>8.1f}"
        )
    return rows, len(union_vectors)


def main() -> int:
    DOCS = _largest_docs(NOTES)
    config = Config.load(HERE.parent / "winnow.json")
    llm = OllamaClient(host=config.ollama_host)
    embedder = build_embedder("ollama", config.embed_model, config.ollama_host)
    pack = find_pack("ai_tooling", Path(config.packs_root))

    # ---- projection, measured -------------------------------------------------
    docs = [(n, (NOTES / n).read_text(encoding="utf-8", errors="replace")) for n in DOCS]
    video_text = VIDEO.read_text(encoding="utf-8", errors="replace")

    doc_calls = sum(len(split_text(t, s)) for _, t in docs for s in NEW_SIZES)
    vid_calls = sum(len(split_text(video_text, s)) for s in VIDEO_SIZES)

    started = time.perf_counter()
    llm.generate(
        config.text_model,
        pack.render_extract_prompt(docs[0][1][:2000]),
        num_ctx=NUM_CTX,
        as_json=True,
    )
    per_call = time.perf_counter() - started
    print(f"measured {per_call:.1f}s for one small call")
    print(f"part A: {doc_calls} calls   part B: {vid_calls} calls")
    print(f"projected {(doc_calls + vid_calls) * per_call / 60:.0f} minutes")
    print("(note: per-call time rises with chunk size, so this understates -- see")
    print(" the projection caveat in CHUNK_SIZE.md)\n")

    # ---- PART A ---------------------------------------------------------------
    prior = json.loads(_require_prior("chunk_size_results.json", "chunk_size_study.py").read_text(encoding="utf-8"))
    results = {}

    print("PART A: same three documents as the first study")
    for size_str, payload in prior["results"].items():
        size = int(size_str)
        texts = payload["texts"]
        results[size] = {
            "claims": payload["claims"],
            "unique": len(texts),
            "seconds": payload["seconds"],
            "texts": texts,
            "vectors": [embedder.embed(t) for t in texts],
        }
        print(f"  reloaded {size:>7,}: {payload['claims']} claims (not re-run)")

    for size in NEW_SIZES:
        all_claims, seconds = [], 0.0
        for name, text in docs:
            claims, elapsed = extract_at(llm, config.text_model, pack, text, size)
            all_claims.extend(claims)
            seconds += elapsed
        unique, vectors = collapse(embedder, all_claims)
        results[size] = {
            "claims": len(all_claims),
            "unique": len(unique),
            "seconds": seconds,
            "texts": unique,
            "vectors": vectors,
        }
        print(f"  measured {size:>7,}: {len(all_claims)} claims, {len(unique)} unique, {seconds:.0f}s")

    all_sizes = sorted(results)
    rows_a, union_a = report("PART A -- written documentation (~150 KB, 3 docs)", results, all_sizes, embedder)

    # ---- PART B ---------------------------------------------------------------
    print(f"\n\nPART B: spoken transcript ({len(video_text) / 1024:.1f} KB)")
    vid_results = {}
    for size in VIDEO_SIZES:
        claims, seconds = extract_at(llm, config.text_model, pack, video_text, size)
        unique, vectors = collapse(embedder, claims)
        vid_results[size] = {
            "claims": len(claims),
            "unique": len(unique),
            "seconds": seconds,
            "texts": unique,
            "vectors": vectors,
        }
        print(f"  measured {size:>7,}: {len(claims)} claims, {len(unique)} unique, {seconds:.0f}s")

    rows_b, union_b = report(
        "PART B -- spoken transcript, independent union", vid_results, VIDEO_SIZES, embedder
    )

    (HERE / "chunk_size_small_results.json").write_text(
        json.dumps(
            {
                "model": config.text_model,
                "embed_model": config.embed_model,
                "duplicate_threshold": DUPLICATE_THRESHOLD,
                "part_a": {"union_size": union_a, "rows": {str(k): v for k, v in rows_a.items()}},
                "part_b": {
                    "union_size": union_b,
                    "transcript_chars": len(video_text),
                    "rows": {str(k): v for k, v in rows_b.items()},
                    "sample_claims": vid_results[1_000]["texts"][:25],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {HERE / 'chunk_size_small_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
