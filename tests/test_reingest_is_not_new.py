"""Ingesting the same material twice must not report it as new the second time.

Found by running the tool for real rather than by reading it. A video already in the corpus,
re-ingested against that corpus: 60 of its 74 claims came back `NEW`.

The mechanism is a correct rule applied in the wrong place. `similarity_search` excludes the
claim being judged (`exclude_claim_id`), because a claim is not evidence about itself --
which is right, and exists for `rejudge`. But re-ingesting produces the SAME claim ids (a
hash of pack, source and text), so on the second pass each claim's nearest neighbour is its
own stored copy, and excluding it leaves only weaker matches. The tool then announces as a
discovery something it has already read.

This is the headline promise inverted: "it tells you what's in the video that you don't
already know", answered with 60 things it already knew.
"""
from __future__ import annotations

import json
from pathlib import Path

from winnow.config import Config
from winnow.models import NOVELTY_NEW
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    """One claim per line of the transcript, deterministically."""

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


# Mutually DISSIMILAR claims. Under the hashing embedder, similarity is token overlap, so
# thirty variations on one sentence all score highly against each other -- and a sibling then
# stands in for the excluded self, hiding the defect entirely. The real corpus that exposed
# this holds claims about unrelated things, where a claim's only close match is its own
# stored copy.
_SUBJECTS = [
    "quantisation formats", "speculative decoding", "paged attention", "rotary embeddings",
    "grouped query attention", "flash attention kernels", "tokeniser vocabularies",
    "KV cache eviction", "prefix caching", "batch scheduling", "tensor parallelism",
    "pipeline parallelism", "LoRA adapters", "gradient checkpointing", "mixed precision",
    "weight streaming", "expert routing", "context extension", "beam search", "sampling",
    "guided decoding", "structured output", "embedding dimensionality", "reranking",
    "chunk overlap", "hybrid retrieval", "index compaction", "vector quantisation",
    "cold start latency", "throughput ceilings",
]
_PREDICATES = [
    "reduce memory pressure", "raise throughput", "cost accuracy", "complicate deployment",
    "help only above a threshold", "interact badly with batching",
]


def _material(tmp_path: Path, subjects=None, name: str = "talk") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    subjects = subjects or _SUBJECTS
    lines = [
        f"{subject} {_PREDICATES[i % len(_PREDICATES)]}"
        for i, subject in enumerate(subjects)
    ]
    (folder / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    return folder


def _pipeline(tmp_path: Path) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        ingest_extra_passes=[],
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor.llm = LineClaimsLLM()
    return pipeline


def test_reingesting_the_same_material_does_not_report_it_as_new(tmp_path):
    folder = _material(tmp_path)

    first = _pipeline(tmp_path)
    try:
        claims, verdicts = first.ingest(folder)
    finally:
        first.close()
    assert len(claims) >= 25, "need a corpus past min_corpus for the second pass to judge"

    second = _pipeline(tmp_path)
    try:
        _, again = second.ingest(folder)
    finally:
        second.close()

    still_new = [v for v in again if v.novelty == NOVELTY_NEW]
    assert not still_new, (
        f"{len(still_new)} of {len(again)} claims from material already in the corpus came "
        "back 'new'. Every one of them is already stored, so the corpus demonstrably "
        "contains it."
    )


def test_a_claim_already_in_the_corpus_says_so(tmp_path):
    """The verdict should explain itself, not just avoid being wrong."""
    folder = _material(tmp_path)

    first = _pipeline(tmp_path)
    try:
        first.ingest(folder)
    finally:
        first.close()

    second = _pipeline(tmp_path)
    try:
        _, again = second.ingest(folder)
    finally:
        second.close()

    assert again, "the second ingest produced no verdicts at all"
    assert any("already" in v.rationale.lower() for v in again), (
        "a claim already in the corpus should say that is why it is known"
    )


def test_genuinely_new_material_is_still_new(tmp_path):
    """The fix must not turn everything into 'known'."""
    first = _pipeline(tmp_path)
    try:
        first.ingest(_material(tmp_path))
    finally:
        first.close()

    other = _material(
        tmp_path,
        subjects=["maritime insurance law", "charterparty arbitration", "salvage awards",
                  "hull underwriting", "demurrage claims", "general average"],
        name="other",
    )

    second = _pipeline(tmp_path)
    try:
        _, verdicts = second.ingest(other)
    finally:
        second.close()

    assert any(v.novelty == NOVELTY_NEW for v in verdicts), (
        "material the corpus has never seen must still be reported as new"
    )
