"""A verdict's coverage must not count the claim it is judging.

`coverage.corpus_claims` is the tool's honesty mechanism: it states how much evidence a
verdict rests on. During `rejudge` the claim being judged is already in the corpus, so it
counted itself and every verdict overstated its evidence by one.

Small in size, but it is the field whose entire purpose is being accurate about evidence,
and it made the two paths disagree: `ingest` judges before storing, so its coverage
correctly excludes the batch, while `rejudge` did not. Same claim, same corpus, two
different numbers.

It also bites hardest exactly at the threshold. A corpus of exactly `min_corpus` claims
reports itself as sufficient during rejudge while every verdict actually rests on one fewer
peer than claimed.
"""

import json
from pathlib import Path

from winnow.config import Config
from winnow.extract import Extractor
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"

SUBJECTS = [
    "quantisation", "attention", "batching", "tokenisation", "caching", "scheduling",
    "embeddings", "retrieval", "sampling", "checkpointing", "sharding", "profiling",
    "compilation", "offloading", "prefetching", "distillation", "pruning", "routing",
    "streaming", "logging", "throttling", "warmup", "eviction", "paging", "fusion",
    "serialisation", "validation", "telemetry", "rebalancing", "prefixing",
]


class OneClaimPerLineLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def build(tmp_path) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        packs_root=str(PACKS_ROOT),
        embed_backend="hashing",
        ingest_extra_passes=[],
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(
        llm=OneClaimPerLineLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    return pipeline


def seed(pipeline, tmp_path, count: int) -> None:
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    for i in range(count):
        (notes / f"n{i:02d}.md").write_text(
            f"{SUBJECTS[i % len(SUBJECTS)]} shifts throughput by {i * 3 + 7} percent",
            encoding="utf-8",
        )
    pipeline.index_notes_folder(notes)


def test_rejudge_coverage_excludes_the_claim_being_judged(tmp_path):
    """The defect: during rejudge each claim counted itself as its own evidence."""
    pipeline = build(tmp_path)
    seed(pipeline, tmp_path, 30)
    stored = pipeline.store.count_claims("ai_tooling")

    verdicts = pipeline.rejudge()

    assert verdicts, "nothing was re-judged"
    for verdict in verdicts:
        assert verdict.coverage.corpus_claims == stored - 1, (
            f"a verdict claims {verdict.coverage.corpus_claims} claims of evidence out of "
            f"{stored} stored, but one of those IS the claim being judged"
        )
    pipeline.close()


def test_ingest_coverage_is_unchanged(tmp_path):
    """The fix must not disturb the path that was already correct.

    `ingest` judges before storing, so its claims are not in the corpus and nothing should
    be subtracted.
    """
    pipeline = build(tmp_path)
    seed(pipeline, tmp_path, 30)
    stored = pipeline.store.count_claims("ai_tooling")

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text(
        "an entirely unrelated assertion about maritime navigation", encoding="utf-8"
    )
    _, verdicts = pipeline.ingest(material)

    assert verdicts[0].coverage.corpus_claims == stored, (
        "an unstored claim must not have anything subtracted for it"
    )
    pipeline.close()


def test_the_two_paths_agree_on_the_same_claim(tmp_path):
    """Same claim, same corpus, two code paths -- the evidence count must match.

    This is what the off-by-one broke: `ingest` said N, `rejudge` said N+1.
    """
    pipeline = build(tmp_path)
    seed(pipeline, tmp_path, 30)

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text("a genuinely novel assertion here", encoding="utf-8")
    _, ingest_verdicts = pipeline.ingest(material)
    from_ingest = ingest_verdicts[0].coverage.corpus_claims

    rejudged = {v.claim_id: v for v in pipeline.rejudge()}
    from_rejudge = rejudged[ingest_verdicts[0].claim_id].coverage.corpus_claims

    assert from_ingest == from_rejudge, (
        f"ingest reported {from_ingest} claims of evidence, rejudge reported "
        f"{from_rejudge} for the same claim against the same corpus"
    )
    pipeline.close()


def test_a_lone_claim_has_no_evidence_at_all(tmp_path):
    """A corpus of one, re-judged, rests on zero peers -- not one."""
    pipeline = build(tmp_path)
    seed(pipeline, tmp_path, 1)

    verdicts = pipeline.rejudge()
    assert verdicts[0].coverage.corpus_claims == 0
    pipeline.close()
