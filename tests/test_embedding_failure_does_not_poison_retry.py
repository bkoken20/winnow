"""A source is complete only when everything it needs has been written.

This morning's fix moved `add_source` after extraction, because a run that died in extraction
still committed the source and `skip_known` then filtered that path out for ever. The fix was
one step short: the EMBEDDING loop runs after `add_source`, so the identical failure one step
later has the identical consequence.

It is the same scenario, too. "The model was never pulled" was the case that prompted the
morning fix -- and if the missing model is the EMBEDDING one rather than the extraction one,
the source is still recorded, the retry still reports "nothing new to index", and the file is
never processed.

The morning's regression test fails extraction, because extraction is the instance I had in
front of me. I fixed the instance and shaped the test around it. These tests fail the
embedding instead, at the first claim and at a later one, on both the index and ingest paths.

Reported as W-001 by an external review, with an executed witness.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.llm import OllamaError
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


class FailingEmbedder:
    """The embedding model was never pulled -- or fails partway through a note."""

    name = "nomic-embed-text"
    backend = "ollama"

    def __init__(self, fail_after: int = 0):
        self.fail_after = fail_after
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        if self.calls > self.fail_after:
            raise OllamaError("model 'nomic-embed-text' not found", status=404)
        return [float(len(text) % 7), 1.0, 0.0]


def _pipeline(tmp_path, embedder=None) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        index_extra_passes=[],
        ingest_extra_passes=[],
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor.llm = LineClaimsLLM()
    if embedder is not None:
        pipeline.judge.embedder = embedder
    return pipeline


@pytest.fixture
def notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "a.md").write_text(
        "quantisation reduces memory pressure\n"
        "speculative decoding needs a matching tokenizer\n"
        "paged attention lowers fragmentation\n",
        encoding="utf-8",
    )
    return folder


@pytest.mark.parametrize("fail_after", [0, 2], ids=["first claim", "a later claim"])
def test_an_embedding_failure_registers_no_source(tmp_path, notes, fail_after):
    pipeline = _pipeline(tmp_path, FailingEmbedder(fail_after=fail_after))
    try:
        with pytest.raises(OllamaError):
            pipeline.index_note(notes / "a.md")
        assert pipeline.store.source_paths("ai_tooling") == set(), (
            "the source was committed before the embeddings that the claims need, so the "
            "retry skips this file for ever"
        )
    finally:
        pipeline.close()


@pytest.mark.parametrize("fail_after", [0, 2], ids=["first claim", "a later claim"])
def test_the_retry_after_pulling_the_model_indexes_the_file(tmp_path, notes, fail_after):
    failed = _pipeline(tmp_path, FailingEmbedder(fail_after=fail_after))
    try:
        with pytest.raises(OllamaError):
            failed.index_notes_folder(notes)
    finally:
        failed.close()

    retried = _pipeline(tmp_path)
    try:
        result = retried.index_notes_folder(notes)
    finally:
        retried.close()

    assert result["files"] == 1, f"the retry skipped the file: {result}"
    assert result["claims"] >= 1, f"the retry stored nothing: {result}"


def test_a_partial_note_leaves_no_claims_behind(tmp_path, notes):
    """Half a note in the corpus is worse than none: it is silently incomplete."""
    pipeline = _pipeline(tmp_path, FailingEmbedder(fail_after=2))
    try:
        with pytest.raises(OllamaError):
            pipeline.index_note(notes / "a.md")
        assert pipeline.store.count_claims("ai_tooling") == 0, (
            "two claims were committed before the third failed, so the corpus holds a "
            "partial note that no retry will ever complete"
        )
    finally:
        pipeline.close()


def test_ingest_has_the_same_boundary(tmp_path):
    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text(
        "throughput is bandwidth bound\nbatching raises utilisation\n", encoding="utf-8"
    )

    pipeline = _pipeline(tmp_path, FailingEmbedder(fail_after=0))
    try:
        with pytest.raises(OllamaError):
            pipeline.ingest(folder)
        assert pipeline.store.source_paths("ai_tooling") == set()
        assert pipeline.store.count_claims("ai_tooling") == 0
    finally:
        pipeline.close()


def test_a_successful_note_is_still_remembered(tmp_path, notes):
    """The guard: skip_known must keep working for runs that actually completed."""
    pipeline = _pipeline(tmp_path)
    try:
        stored = pipeline.index_note(notes / "a.md")
        assert stored >= 1
        assert len(pipeline.store.source_paths("ai_tooling")) == 1
    finally:
        pipeline.close()
