"""A run that failed must not make the retry a no-op.

Found immediately after fixing the "model not pulled" message, by doing what a user would do
next: fix the problem and run the command again. Winnow said:

    nothing new to index
    exit=0

Every file had been skipped. `index_note` records the SOURCE before it extracts anything, so
a run that dies in extraction still commits the source row -- and `skip_known` then filters
that path out for ever. The corpus holds one source and zero claims, and the tool reports
success while doing nothing.

The failure it follows is the likeliest first-run failure there is, so the sequence
"install, forget to pull, fail, pull, retry, silently get nothing" is the default path a
stranger takes.

A source is recorded when it has been processed, not when processing was attempted.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.llm import OllamaError
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class DeadModelLLM:
    """Ollama answering 404 because the model was never pulled."""

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        raise OllamaError(f"model {model!r} not found", status=404)


class WorkingLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _pipeline(tmp_path, llm) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        index_extra_passes=[],
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor.llm = llm
    return pipeline


@pytest.fixture
def notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "a.md").write_text(
        "quantisation reduces memory pressure on consumer cards", encoding="utf-8"
    )
    return folder


def test_a_failed_index_registers_no_source(tmp_path, notes):
    pipeline = _pipeline(tmp_path, DeadModelLLM())
    try:
        with pytest.raises(OllamaError):
            pipeline.index_note(notes / "a.md")
        assert pipeline.store.source_paths("ai_tooling") == set(), (
            "the source was recorded before extraction ran, so a failed run marks the file "
            "as already handled"
        )
    finally:
        pipeline.close()


def test_the_retry_after_fixing_the_model_actually_indexes(tmp_path, notes):
    """The whole point: fix the cause, run it again, and get your corpus."""
    failed = _pipeline(tmp_path, DeadModelLLM())
    try:
        with pytest.raises(OllamaError):
            failed.index_notes_folder(notes)
    finally:
        failed.close()

    retried = _pipeline(tmp_path, WorkingLLM())
    try:
        result = retried.index_notes_folder(notes)
    finally:
        retried.close()

    assert result["files"] == 1, f"the retry skipped the file: {result}"
    assert result["claims"] >= 1, f"the retry stored nothing: {result}"


def test_a_failed_ingest_registers_no_source(tmp_path):
    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text("a claim about throughput", encoding="utf-8")

    pipeline = _pipeline(tmp_path, DeadModelLLM())
    try:
        with pytest.raises(OllamaError):
            pipeline.ingest(folder)
        assert pipeline.store.source_paths("ai_tooling") == set()
    finally:
        pipeline.close()


def test_a_successful_run_does_register_its_source(tmp_path, notes):
    """The fix must not stop successful runs being remembered -- that is what skip_known is for."""
    pipeline = _pipeline(tmp_path, WorkingLLM())
    try:
        pipeline.index_note(notes / "a.md")
        assert len(pipeline.store.source_paths("ai_tooling")) == 1
    finally:
        pipeline.close()
