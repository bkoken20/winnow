"""Are the extracted claims actually faithful to the source?

Every measurement so far counts what was found, never whether it was true. A pass that
doubled the claim count while halving accuracy would look identical in those tables -- so
the whole multi-pass result rests on an untested assumption: that the extra claims smaller
chunks find are real rather than invented.

WHAT IS BEING MEASURED
    Faithfulness to the source, not truth about the world. If the speaker is wrong and the
    claim repeats him accurately, the extraction is correct. Four verdicts:

      SUPPORTED    the source says this
      DISTORTED    the source says something close, but this changes a number, a
                   condition, or the subject it applies to
      UNSUPPORTED  the source does not say this
      UNCLEAR      the retrieved excerpts are insufficient to tell

    DISTORTED is the interesting category. Chunking can separate a claim's subject from its
    qualifier, so an extractor may confidently attach the right number to the wrong model.

INDEPENDENCE
    The judge (gemma3:27b) is a different family and size from the extractor
    (qwen2.5:14b-instruct). A model grading its own output would share its blind spots.
    A human-graded subsample calibrates the judge in a second step -- if the judge and a
    human disagree often, the judge's verdicts on the full set mean nothing.

RETRIEVAL
    The judge sees the three transcript windows nearest the claim, not the whole source, so
    the call stays cheap. Three windows rather than one because a claim's support can sit
    across a boundary; retrieving too narrowly would manufacture false UNSUPPORTED verdicts.
"""

from __future__ import annotations

import json
import os
import re
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


from winnow.config import Config
from winnow.embed import build_embedder, cosine_similarity
from winnow.llm import OllamaClient

JUDGE_MODEL = "gemma3:27b"
JUDGE_NUM_CTX = 8192
WINDOW = 1_200
OVERLAP = 600
TOP_K = 3

VIDEO = _env_path("WINNOW_TRANSCRIPT", "a plain-text transcript file")

JUDGE_PROMPT = """You are checking whether a claim is faithful to a source transcript.

You are NOT judging whether the claim is true in the world. You are judging only whether the
source says it. If the speaker is mistaken and the claim repeats him accurately, that is
SUPPORTED.

SOURCE EXCERPTS (the passages most similar to the claim):
__EXCERPTS__

CLAIM:
__CLAIM__

Answer with JSON only:

{"verdict": "SUPPORTED" | "DISTORTED" | "UNSUPPORTED" | "UNCLEAR", "reason": "one short sentence"}

Definitions:
- SUPPORTED: the excerpts state this, allowing for rewording.
- DISTORTED: the excerpts say something close but the claim changes a number, a condition,
  or which thing it applies to. Attaching a real figure to the wrong subject is DISTORTED.
- UNSUPPORTED: the excerpts do not say this at all.
- UNCLEAR: the excerpts are not enough to decide.

Be strict about numbers and about which model, tool or hardware a statement applies to."""


def windows(text: str) -> list[str]:
    step = WINDOW - OVERLAP
    return [text[i : i + WINDOW] for i in range(0, max(1, len(text) - OVERLAP), step)]


def parse_verdict(raw: str) -> tuple[str, str]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return "PARSE_FAIL", raw[:80]
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return "PARSE_FAIL", raw[:80]
    verdict = str(obj.get("verdict", "")).upper().strip()
    if verdict not in ("SUPPORTED", "DISTORTED", "UNSUPPORTED", "UNCLEAR"):
        return "PARSE_FAIL", str(obj)[:80]
    return verdict, str(obj.get("reason", ""))[:160]


def main() -> int:
    config = Config.load(HERE.parent / "winnow.json")
    llm = OllamaClient(host=config.ollama_host)
    embedder = build_embedder("ollama", config.embed_model, config.ollama_host)

    text = VIDEO.read_text(encoding="utf-8", errors="replace")
    chunks = windows(text)
    print(f"transcript {len(text) / 1024:.1f} KB -> {len(chunks)} retrieval windows")
    chunk_vectors = [embedder.embed(c) for c in chunks]

    data = json.loads((HERE / "two_pass_results.json").read_text(encoding="utf-8"))
    by_size = {int(k): v for k, v in data["texts"]["video"].items()}
    total = sum(len(v) for v in by_size.values())
    print(f"{total} claims across {len(by_size)} pass sizes\n")

    started = time.perf_counter()
    records = []
    for size in sorted(by_size):
        for claim in by_size[size]:
            vector = embedder.embed(claim)
            ranked = sorted(
                range(len(chunks)),
                key=lambda i: cosine_similarity(vector, chunk_vectors[i]),
                reverse=True,
            )[:TOP_K]
            excerpts = "\n\n---\n\n".join(chunks[i] for i in sorted(ranked))
            prompt = JUDGE_PROMPT.replace("__EXCERPTS__", excerpts).replace("__CLAIM__", claim)
            raw = llm.generate(JUDGE_MODEL, prompt, num_ctx=JUDGE_NUM_CTX, as_json=True)
            verdict, reason = parse_verdict(raw)
            records.append(
                {"size": size, "claim": claim, "verdict": verdict, "reason": reason,
                 "excerpt_ids": sorted(ranked)}
            )
        done = len(records)
        print(f"  judged {done}/{total} ({time.perf_counter() - started:.0f}s elapsed)")

    # ---- results by pass size ------------------------------------------------
    print(f"\n{'=' * 74}\nFAITHFULNESS BY CHUNK SIZE   (judge: {JUDGE_MODEL})\n{'=' * 74}")
    print(f"{'chunk':>8} {'n':>5} {'supported':>11} {'distorted':>11} {'unsupported':>13} {'unclear':>9}")
    print("-" * 62)
    summary = {}
    for size in sorted(by_size):
        rows = [r for r in records if r["size"] == size]
        counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in
                  ("SUPPORTED", "DISTORTED", "UNSUPPORTED", "UNCLEAR", "PARSE_FAIL")}
        n = len(rows)
        summary[size] = {"n": n, **counts}
        pct = lambda k: f"{100 * counts[k] / n:.0f}%" if n else "-"
        print(f"{size:>8,} {n:>5} {pct('SUPPORTED'):>11} {pct('DISTORTED'):>11} "
              f"{pct('UNSUPPORTED'):>13} {pct('UNCLEAR'):>9}")

    overall = {v: sum(1 for r in records if r["verdict"] == v) for v in
               ("SUPPORTED", "DISTORTED", "UNSUPPORTED", "UNCLEAR", "PARSE_FAIL")}
    print(f"\noverall: {overall}")

    # ---- a blind sample for human grading ------------------------------------
    import random
    random.seed(11)
    sample = random.sample(records, min(25, len(records)))
    blind = [
        {"n": i, "claim": r["claim"], "excerpts": "\n---\n".join(chunks[j] for j in r["excerpt_ids"])}
        for i, r in enumerate(sample)
    ]
    (HERE / "correctness_blind_sample.json").write_text(
        json.dumps(blind, indent=2), encoding="utf-8"
    )
    (HERE / "correctness_judge_verdicts.json").write_text(
        json.dumps([{"n": i, "verdict": r["verdict"], "reason": r["reason"]}
                    for i, r in enumerate(sample)], indent=2),
        encoding="utf-8",
    )
    (HERE / "correctness_results.json").write_text(
        json.dumps({"judge_model": JUDGE_MODEL, "by_size": {str(k): v for k, v in summary.items()},
                    "overall": overall, "records": records}, indent=2),
        encoding="utf-8",
    )
    print(f"\nblind sample for human grading: {HERE / 'correctness_blind_sample.json'}")
    print(f"(judge verdicts for the same sample held separately, for comparison after)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
