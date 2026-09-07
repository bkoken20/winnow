"""Does forcing the judge to quote its evidence make it detect distortions?

The lenient judge (see CORRECTNESS.md) reported zero DISTORTED across 85 claims and missed
all three distortions the reference grading found. This tests one hypothesis about why: it
was asked to assess, not to prove, so it could agree without committing to anything checkable.

Two changes:

1. The judge must QUOTE the span that supports the claim, verbatim from the excerpts. A
   claim it cannot quote support for cannot be waved through.
2. The quote is then VERIFIED programmatically -- a normalised substring check against the
   source. This is not another model's opinion; either the span is in the text or it is not.
   A judge that invents its support is caught by string matching.

The prompt describes *strengthening* as a failure mode generically. It deliberately does not
mention the three specific errors the reference grading found, which would be fitting the
prompt to the test set.

RISK BEING MEASURED IN BOTH DIRECTIONS: an adversarial prompt can trade one error for
another, flagging faithful claims as distorted. Detection of the three known distortions is
useless if it comes with a pile of false alarms, so both are counted.
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
from winnow.llm import OllamaClient

JUDGE_MODEL = "gemma3:27b"
JUDGE_NUM_CTX = 8192
WINDOW = 1_200
OVERLAP = 600
TOP_K = 3

VIDEO = _env_path("WINNOW_TRANSCRIPT", "a plain-text transcript file")

STRICT_PROMPT = """Your job is to check a claim against a source, strictly. Assume the claim
may be subtly wrong until the source proves otherwise.

You are NOT judging whether the claim is true in the world. Only whether the source says it.
If the speaker is mistaken and the claim repeats him accurately, that is SUPPORTED.

SOURCE EXCERPTS:
__EXCERPTS__

CLAIM:
__CLAIM__

Work in this order:

1. Find the exact words in the source that support the claim. Copy them VERBATIM, character
   for character, from the excerpts above. Do not paraphrase, correct, tidy or complete them.
   If no such words exist, the quote is an empty string.
2. Compare the claim against that quote, word by word. Check in particular:
   - every number, and what each number is attached to
   - which model, tool, machine or component the statement is about
   - any condition or qualifier the source attaches, and whether the claim keeps it
   - whether the claim is STRONGER than the quote. A source saying something is "not slow"
     does not support a claim that it is "fast". A source describing what one machine HAS
     does not support a claim about what is REQUIRED. Losing a hedge is a real difference.
3. Decide.

Return JSON only:

{"quote": "verbatim words from the source, or empty string",
 "verdict": "SUPPORTED" | "DISTORTED" | "UNSUPPORTED",
 "reason": "one short sentence naming the specific difference, or confirming there is none"}

- SUPPORTED: the quote states the claim, allowing only for rewording that changes nothing.
- DISTORTED: the quote is about the same thing but the claim alters a number, a subject, a
  condition, or the strength of the statement.
- UNSUPPORTED: nothing in the excerpts addresses this claim.

A claim you cannot produce a verbatim quote for is never SUPPORTED."""


def windows(text: str) -> list[str]:
    step = WINDOW - OVERLAP
    return [text[i : i + WINDOW] for i in range(0, max(1, len(text) - OVERLAP), step)]


def normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def quote_is_real(quote: str, excerpts: str) -> bool:
    """Is the quoted span actually present in the source? Not a model's opinion."""
    q = normalise(quote)
    if len(q) < 15:  # too short to verify meaningfully
        return False
    return q in normalise(excerpts)


def parse(raw: str) -> tuple[str, str, str]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return "PARSE_FAIL", "", raw[:80]
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return "PARSE_FAIL", "", raw[:80]
    verdict = str(obj.get("verdict", "")).upper().strip()
    if verdict not in ("SUPPORTED", "DISTORTED", "UNSUPPORTED"):
        return "PARSE_FAIL", "", str(obj)[:80]
    return verdict, str(obj.get("quote", "")), str(obj.get("reason", ""))[:200]


def main() -> int:
    config = Config.load(HERE.parent / "winnow.json")
    llm = OllamaClient(host=config.ollama_host)
    embedder = build_embedder("ollama", config.embed_model, config.ollama_host)

    text = VIDEO.read_text(encoding="utf-8", errors="replace")
    chunks = windows(text)
    chunk_vectors = [embedder.embed(c) for c in chunks]

    data = json.loads(_require_prior("two_pass_results.json", "two_pass_study.py").read_text(encoding="utf-8"))
    by_size = {int(k): v for k, v in data["texts"]["video"].items()}
    total = sum(len(v) for v in by_size.values())
    print(f"{total} claims, strict prompt, judge={JUDGE_MODEL}\n")

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
            prompt = STRICT_PROMPT.replace("__EXCERPTS__", excerpts).replace("__CLAIM__", claim)
            raw = llm.generate(JUDGE_MODEL, prompt, num_ctx=JUDGE_NUM_CTX, as_json=True)
            verdict, quote, reason = parse(raw)
            records.append({
                "size": size, "claim": claim, "verdict": verdict, "quote": quote,
                "quote_verified": quote_is_real(quote, excerpts), "reason": reason,
            })
        print(f"  {len(records)}/{total} ({time.perf_counter() - started:.0f}s)")

    # ---- quote verification --------------------------------------------------
    supported = [r for r in records if r["verdict"] == "SUPPORTED"]
    verified = [r for r in supported if r["quote_verified"]]
    print(f"\nquote verification: {len(verified)}/{len(supported)} SUPPORTED verdicts cite a "
          f"span actually present in the source ({100 * len(verified) / max(1, len(supported)):.0f}%)")

    # ---- by chunk size -------------------------------------------------------
    print(f"\n{'chunk':>8} {'n':>5} {'supported':>11} {'distorted':>11} {'unsupported':>13}")
    print("-" * 50)
    by_size_rows = {}
    for size in sorted(by_size):
        rows = [r for r in records if r["size"] == size]
        c = {v: sum(1 for r in rows if r["verdict"] == v)
             for v in ("SUPPORTED", "DISTORTED", "UNSUPPORTED", "PARSE_FAIL")}
        n = len(rows)
        by_size_rows[size] = {"n": n, **c}
        f = lambda k: f"{100 * c[k] / n:.0f}%" if n else "-"
        print(f"{size:>8,} {n:>5} {f('SUPPORTED'):>11} {f('DISTORTED'):>11} {f('UNSUPPORTED'):>13}")

    # ---- against the reference-graded sample ---------------------------------
    human = json.loads(_require_prior("correctness_human_grades.json", "correctness_study.py (then grade the sample)").read_text(encoding="utf-8"))["grades"]
    sample = json.load(open(_require_prior("correctness_blind_sample.json", "correctness_study.py"), encoding="utf-8"))
    lenient = {str(r["n"]): r["verdict"]
               for r in json.load(open(_require_prior("correctness_judge_verdicts.json", "correctness_study.py"), encoding="utf-8"))}
    strict_by_claim = {r["claim"]: r for r in records}

    print(f"\n{'=' * 92}\nAGAINST THE HAND-GRADED SAMPLE (n=25)\n{'=' * 92}")
    agree_strict = agree_lenient = 0
    known_distortions = [k for k in human if human[k]["verdict"] == "DISTORTED"]
    caught_strict = caught_lenient = 0
    false_alarms = []

    for r in sample:
        k = str(r["n"])
        hv = human[k]["verdict"]
        sv = strict_by_claim.get(r["claim"], {}).get("verdict", "MISSING")
        lv = lenient[k]
        agree_strict += hv == sv
        agree_lenient += hv == lv
        if hv == "DISTORTED":
            caught_strict += sv == "DISTORTED"
            caught_lenient += lv == "DISTORTED"
        elif hv == "SUPPORTED" and sv in ("DISTORTED", "UNSUPPORTED"):
            false_alarms.append((k, r["claim"], sv, strict_by_claim[r["claim"]]["reason"]))

    print(f"agreement with hand grades:  strict {agree_strict}/25 ({100*agree_strict/25:.0f}%)"
          f"   lenient {agree_lenient}/25 ({100*agree_lenient/25:.0f}%)")
    print(f"distortions caught:          strict {caught_strict}/{len(known_distortions)}"
          f"   lenient {caught_lenient}/{len(known_distortions)}")
    print(f"false alarms on faithful claims: strict {len(false_alarms)}")

    if false_alarms:
        print("\nFALSE ALARMS (reference grade SUPPORTED, strict judge disagreed):")
        for k, claim, v, reason in false_alarms:
            print(f"  [{k}] {v}: {claim[:80]}")
            print(f"        {reason[:110]}")

    print("\nTHE THREE KNOWN DISTORTIONS:")
    for k in known_distortions:
        claim = next(r["claim"] for r in sample if str(r["n"]) == k)
        sr = strict_by_claim.get(claim, {})
        print(f"  [{k}] strict={sr.get('verdict','?'):<12} lenient={lenient[k]}")
        print(f"        claim : {claim[:96]}")
        print(f"        reason: {sr.get('reason','')[:110]}")

    (HERE / "strict_judge_results.json").write_text(
        json.dumps({"judge_model": JUDGE_MODEL, "by_size": {str(k): v for k, v in by_size_rows.items()},
                    "agreement_strict": agree_strict, "agreement_lenient": agree_lenient,
                    "distortions_caught_strict": caught_strict,
                    "distortions_caught_lenient": caught_lenient,
                    "false_alarms": len(false_alarms), "records": records}, indent=2),
        encoding="utf-8")
    print(f"\nwritten: {HERE / 'strict_judge_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
