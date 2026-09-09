"""The score beside a re-ingested claim must mean what the score means everywhere else.

`docs/PARAMETERS.md` defines it precisely: the cosine similarity between this claim and the
nearest OTHER claim in the corpus, the claim's own copy excluded. The already-in-the-corpus
verdict printed a flat `1.0` instead -- a sentinel standing for "this exact claim is stored",
in the column documented to hold a measurement.

It is avoidable, too: that verdict already runs the neighbour search, so the real number is
in hand and was being thrown away.

The verdict itself is right and stays: a claim already in the corpus is known regardless of
what else the corpus holds. That route to `known` simply does not consult the similarity
thresholds, which is now said in the documentation rather than implied by a magic number.

Reported by an external review.
"""
from __future__ import annotations

import json
from pathlib import Path

from winnow.config import Config
from winnow.models import NOVELTY_KNOWN
from winnow.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent.parent
PACKS_ROOT = ROOT / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


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


def _material(tmp_path: Path) -> Path:
    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text(
        "\n".join(f"{s} changes the picture under load" for s in _SUBJECTS), encoding="utf-8"
    )
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


def _reingest(tmp_path):
    folder = _material(tmp_path)
    first = _pipeline(tmp_path)
    try:
        first.ingest(folder)
    finally:
        first.close()
    second = _pipeline(tmp_path)
    try:
        return second.ingest(folder)[1]
    finally:
        second.close()


def test_the_score_is_a_real_similarity_not_a_sentinel(tmp_path, capsys):
    verdicts = _reingest(tmp_path)
    capsys.readouterr()

    assert verdicts, "nothing was re-ingested"
    flat = [v for v in verdicts if v.similarity == 1.0]
    assert not flat, (
        f"{len(flat)} of {len(verdicts)} re-ingested claims report a similarity of exactly "
        "1.0, which is a sentinel rather than the measurement the column documents"
    )


def test_the_score_matches_the_nearest_other_claim(tmp_path, capsys):
    """The documented definition, checked against the neighbours the verdict carries."""
    verdicts = _reingest(tmp_path)
    capsys.readouterr()

    for verdict in verdicts:
        expected = verdict.neighbours[0].similarity if verdict.neighbours else 0.0
        assert verdict.similarity == expected, (
            f"reported {verdict.similarity} but the nearest other claim is at {expected}"
        )


def test_the_verdict_is_still_known_and_says_why(tmp_path, capsys):
    """The guard: the reason for `known` here is storage, not the threshold."""
    verdicts = _reingest(tmp_path)
    capsys.readouterr()

    assert all(v.novelty == NOVELTY_KNOWN for v in verdicts)
    assert all("already" in v.rationale.lower() for v in verdicts), (
        "with a real similarity in the column, the rationale is the only thing left saying "
        "this is known because it is stored rather than because it scored high"
    )


def test_the_documentation_admits_this_route_to_known():
    """A `known` verdict below the documented cutoff needs explaining, not hiding."""
    parameters = (ROOT / "docs" / "PARAMETERS.md").read_text(encoding="utf-8")
    section = parameters.split("## Reading the score")[1].split("\n## ")[0].lower()

    assert "already" in section, (
        "the score section defines known by threshold; a claim already in the corpus is "
        "known whatever it scores, and that exception has to be stated"
    )
