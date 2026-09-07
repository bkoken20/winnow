"""End-to-end wiring, with no model server involved.

These exist because every module below was individually green while `ingest` still crashed
on its first real run: the verdict was written before the claim it referenced, violating a
foreign key. Unit tests cannot catch an ordering fault between two components that were
each correct on their own.
"""

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.extract import Extractor
from winnow.models import NOVELTY_KNOWN, NOVELTY_UNKNOWN
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class OneClaimPerLineLLM:
    """Stands in for an extraction model: each non-empty line becomes a claim."""

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        claims = [
            {"claim": line.strip(), "kind": "observation"}
            for line in body.splitlines()
            if line.strip()
        ][:5]
        return json.dumps({"claims": claims})


def build(tmp_path, min_corpus_override=None) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(
        llm=OneClaimPerLineLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    if min_corpus_override is not None:
        pipeline.judge.config.min_corpus = min_corpus_override
    return pipeline


SUBJECTS = [
    "quantisation", "attention", "batching", "tokenisation", "caching", "scheduling",
    "embeddings", "retrieval", "sampling", "checkpointing", "sharding", "profiling",
    "compilation", "offloading", "prefetching", "distillation", "pruning", "routing",
    "streaming", "logging", "throttling", "warmup", "eviction", "paging", "fusion",
    "serialisation", "validation", "telemetry", "rebalancing", "prefixing",
]
EFFECTS = [
    "cuts memory use", "raises throughput", "adds latency", "reduces accuracy",
    "improves stability", "increases VRAM pressure",
]


def _note_text(i: int) -> str:
    """Genuinely distinct claims.

    Notes that differ only by an index number are near-duplicates of each other, and the
    corpus now suppresses those on insert -- correctly. Fixtures that need N stored claims
    must therefore say N different things.
    """
    return f"{SUBJECTS[i % len(SUBJECTS)]} {EFFECTS[i % len(EFFECTS)]} on consumer hardware"


def write_notes(folder: Path, count: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (folder / f"note{i:02d}.md").write_text(
            _note_text(i), encoding="utf-8"
        )


def test_ingest_persists_claims_and_verdicts(tmp_path):
    """The regression: a verdict written before its claim violated a foreign key."""
    pipeline = build(tmp_path)
    write_notes(tmp_path / "notes", 30)
    pipeline.index_notes_folder(tmp_path / "notes")

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text("a brand new assertion entirely", encoding="utf-8")

    claims, verdicts = pipeline.ingest(material)

    assert len(claims) == 1
    assert len(verdicts) == 1
    stored = pipeline.store.latest_verdicts("ai_tooling")
    assert len(stored) == 1  # the verdict really landed, not just the object
    pipeline.close()


def test_index_then_ingest_recognises_a_restatement(tmp_path):
    pipeline = build(tmp_path)
    write_notes(tmp_path / "notes", 30)
    pipeline.index_notes_folder(tmp_path / "notes")

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text(
        _note_text(7), encoding="utf-8"
    )
    _, verdicts = pipeline.ingest(material)

    assert verdicts[0].novelty == NOVELTY_KNOWN
    assert verdicts[0].similarity > 0.99
    pipeline.close()


def test_thin_corpus_reports_unknown_through_the_pipeline(tmp_path):
    pipeline = build(tmp_path)
    write_notes(tmp_path / "notes", 3)  # far below the pack minimum
    pipeline.index_notes_folder(tmp_path / "notes")

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text("some assertion", encoding="utf-8")
    _, verdicts = pipeline.ingest(material)

    assert verdicts[0].novelty == NOVELTY_UNKNOWN
    pipeline.close()


def test_ingest_refuses_media_without_a_transcript(tmp_path):
    """Winnow does not transcribe; the error must say so rather than failing obscurely."""
    pipeline = build(tmp_path)
    material = tmp_path / "talk"
    material.mkdir()
    (material / "video.mp4").write_bytes(b"\x00")

    with pytest.raises(FileNotFoundError) as exc:
        pipeline.ingest(material)
    message = str(exc.value)
    assert "video.mp4" in message
    assert "ACQUISITION.md" in message
    pipeline.close()


def test_reindexing_skips_files_already_in_the_corpus(tmp_path):
    pipeline = build(tmp_path)
    write_notes(tmp_path / "notes", 5)
    first = pipeline.index_notes_folder(tmp_path / "notes")
    second = pipeline.index_notes_folder(tmp_path / "notes")

    assert first["files"] == 5
    assert second["files"] == 0
    pipeline.close()


def test_rejudge_revisits_every_claim(tmp_path):
    pipeline = build(tmp_path)
    write_notes(tmp_path / "notes", 30)
    pipeline.index_notes_folder(tmp_path / "notes")

    verdicts = pipeline.rejudge()

    assert len(verdicts) == 30
    assert all(v.judge.pack_version for v in verdicts)
    pipeline.close()
