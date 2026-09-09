"""A run the gate refuses must leave the corpus exactly as it found it.

`index_notes_folder` measures by indexing one real file -- and indexing commits. So the
sample's source and claims were written BEFORE the projection was compared against the
budget. When the gate then refused, the user was told nothing had started while the corpus
had already changed.

The gate's whole promise is that you see a number before anything happens. "Anything" has to
include the measurement itself.

Reported by an external review. The fix reuses the shape from the embedding-failure repair:
do the fallible, expensive work first, commit only once the decision is made.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.cost import RunRefused
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


@pytest.fixture(autouse=True)
def gate_fires_on_anything(monkeypatch):
    """Trip the gate on any run, so these tests are about ORDER rather than duration.

    The first version of this file made the model sleep, hoping to project past the real
    120-second threshold. A six-file folder projects to about two seconds however slow one
    call is, so the gate never fired and every assertion failed on "DID NOT RAISE" -- red,
    but for the wrong reason. The threshold arithmetic is tested elsewhere; what is under
    test here is whether storing happens before gating.
    """
    from winnow import pipeline as pipeline_module

    real = pipeline_module.gate

    def always_gate(projection, accepted, *, threshold_seconds=120.0):
        return real(projection, accepted, threshold_seconds=0.0)

    monkeypatch.setattr(pipeline_module, "gate", always_gate)


def _pipeline(tmp_path) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        index_extra_passes=[],
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor.llm = LineClaimsLLM()
    return pipeline


@pytest.fixture
def notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    for i in range(6):
        (folder / f"n{i}.md").write_text(
            "\n".join(f"subject {i}{j} behaves differently under load" for j in range(8)),
            encoding="utf-8",
        )
    return folder


def test_a_refused_run_stores_nothing(notes, tmp_path, capsys):
    pipeline = _pipeline(tmp_path)
    try:
        with pytest.raises(RunRefused):
            pipeline.index_notes_folder(notes, accept_minutes=None)
        capsys.readouterr()

        assert pipeline.store.count_claims("ai_tooling") == 0, (
            "the sample was indexed and committed before the budget was checked, so a run "
            "the gate refused still changed the corpus"
        )
        assert pipeline.store.source_paths("ai_tooling") == set(), (
            "and the sample was recorded, so a later accepted run skips it"
        )
    finally:
        pipeline.close()


def test_the_refusal_still_reports_a_measured_projection(notes, tmp_path, capsys):
    """The measurement must still happen -- it is what makes the number real."""
    pipeline = _pipeline(tmp_path)
    try:
        with pytest.raises(RunRefused) as exc:
            pipeline.index_notes_folder(notes, accept_minutes=None)
    finally:
        pipeline.close()

    message = str(exc.value)
    assert "measured" in message, f"the projection must come from a timed unit: {message!r}"
    assert "--accept-minutes" in message


def test_accepting_the_budget_indexes_every_file(notes, tmp_path, capsys):
    """The guard: refusing cleanly must not cost the accepted path its sample."""
    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(notes, accept_minutes=600)
        capsys.readouterr()
    finally:
        pipeline.close()

    assert result["files"] == 6, f"a file was dropped: {result}"
    assert result["claims"] > 0

    reopened = _pipeline(tmp_path)
    try:
        assert len(reopened.store.source_paths("ai_tooling")) == 6, (
            "every indexed file must be recorded, or the next run redoes it"
        )
    finally:
        reopened.close()


def test_a_refused_run_can_be_retried_in_full(notes, tmp_path, capsys):
    """After a refusal, accepting must process the whole folder, sample included."""
    first = _pipeline(tmp_path)
    try:
        with pytest.raises(RunRefused):
            first.index_notes_folder(notes, accept_minutes=None)
    finally:
        first.close()
    capsys.readouterr()

    second = _pipeline(tmp_path)
    try:
        result = second.index_notes_folder(notes, accept_minutes=600)
    finally:
        second.close()
    capsys.readouterr()

    assert result["files"] == 6, (
        f"the refused run left the sample marked as done, so the retry skipped it: {result}"
    )
