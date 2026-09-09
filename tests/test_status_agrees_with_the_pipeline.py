"""`status` and the pipeline asked the same question and compared different things.

The pipeline refuses a corpus whose stored embedding model is not the one now configured. It
compares against `embedder.name` — what the embedder in use actually calls itself. `status`
does the same check by hand and compares against `config.embed_model` — what the file says.

For the Ollama backend those two strings are equal, so the difference never showed. For the
hashing backend they are not:

    backend=hashing   config.embed_model='nomic-embed-text'   embedder.name='hashing-256'

So on a corpus built with `embed_backend: "hashing"`, and configured with exactly the
settings that built it, `winnow status` reports:

    UNUSABLE -- these claims were embedded with 'hashing-256', not 'nomic-embed-text'.

and exits 6. Nothing is wrong. The corpus and the configuration agree, and the command whose
job is to tell you whether they agree says they do not — while `index` and `ingest` on the
same corpus run happily, because they ask the embedder rather than the file.

Two commands answering one question two ways is not a wording problem: it is one question
with two implementations, and the second one drifted. The comparison now lives in a single
function that both callers use.

Reported by an external review as a comparison mismatch; the false `UNUSABLE` is what it
turns out to cause.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.embed import build_embedder
from winnow.pipeline import CorpusEmbeddingMismatch, Pipeline, foreign_embed_models
from winnow.store import Store
from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _config_file(tmp_path, corpus: Path, **overrides) -> Path:
    body = {
        "pack": "ai_tooling",
        "corpus_path": str(corpus),
        "embed_backend": "hashing",
        "packs_root": str(PACKS_ROOT),
    }
    body.update(overrides)
    path = tmp_path / "winnow.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _build_corpus(tmp_path, corpus: Path, backend: str = "hashing") -> None:
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "a.md").write_text("throughput is bandwidth bound", encoding="utf-8")

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(corpus),
            embed_backend=backend,
            packs_root=str(PACKS_ROOT),
            index_extra_passes=[],
        )
    )
    pipeline.extractor.llm = LineClaimsLLM()
    try:
        pipeline.index_notes_folder(notes, accept_minutes=600)
    finally:
        pipeline.close()


def test_status_does_not_cry_mismatch_over_a_corpus_it_just_built(tmp_path, capsys):
    corpus = tmp_path / "winnow.db"
    _build_corpus(tmp_path, corpus)
    capsys.readouterr()

    code = cli.main(["status", "--config", str(_config_file(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert "UNUSABLE" not in said, (
        f"the configuration that built this corpus is reported as unable to read it: {said}"
    )
    assert code == 0, f"README documents 6 for a real mismatch, not for agreement: {said!r}"


def test_status_still_reports_a_real_mismatch(tmp_path, capsys):
    """The mirror: silencing the false alarm must not silence the true one."""
    corpus = tmp_path / "winnow.db"
    _build_corpus(tmp_path, corpus)
    capsys.readouterr()

    config = _config_file(tmp_path, corpus, embed_backend="ollama",
                          embed_model="some-other-model")
    code = cli.main(["status", "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert "UNUSABLE" in said, f"a genuine mismatch must still be reported: {said!r}"
    assert code == 6
    assert "hashing-256" in said, "name what is actually in the corpus"


def test_the_pipeline_and_status_agree_on_the_same_corpus(tmp_path, capsys):
    """One question, one answer. They disagreed for every hashing corpus."""
    corpus = tmp_path / "winnow.db"
    _build_corpus(tmp_path, corpus)
    capsys.readouterr()

    config = Config(
        pack="ai_tooling",
        corpus_path=str(corpus),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
    )
    pipeline = Pipeline.build(config)  # raises if IT thinks there is a mismatch
    pipeline.close()
    capsys.readouterr()

    code = cli.main(["status", "--config", str(_config_file(tmp_path, corpus))])
    capsys.readouterr()
    assert code == 0, "the pipeline opened this corpus and status called it unusable"


# -- the shared comparison ---------------------------------------------------------------


def test_the_comparison_is_one_function(tmp_path):
    """Both callers ask this. Two copies is how the two answers diverged."""
    corpus = tmp_path / "winnow.db"
    _build_corpus(tmp_path, corpus)

    store = Store.open_readonly(str(corpus))
    try:
        hashing = build_embedder("hashing")
        assert foreign_embed_models(store, "ai_tooling", hashing.name) == []

        other = build_embedder("ollama", "some-other-model", "http://localhost:11434")
        assert foreign_embed_models(store, "ai_tooling", other.name) == ["hashing-256"]
    finally:
        store.close()


def test_an_empty_corpus_has_no_foreign_models(tmp_path):
    corpus = tmp_path / "winnow.db"
    Store(str(corpus)).close()

    store = Store.open_readonly(str(corpus))
    try:
        assert foreign_embed_models(store, "ai_tooling", "anything") == []
    finally:
        store.close()


def test_the_pipeline_still_refuses_a_foreign_corpus(tmp_path, capsys):
    """The guard the shared function must not weaken."""
    corpus = tmp_path / "winnow.db"
    _build_corpus(tmp_path, corpus)
    capsys.readouterr()

    with pytest.raises(CorpusEmbeddingMismatch) as raised:
        Pipeline.build(
            Config(
                pack="ai_tooling",
                corpus_path=str(corpus),
                embed_backend="ollama",
                embed_model="some-other-model",
                packs_root=str(PACKS_ROOT),
            )
        )
    capsys.readouterr()

    assert "hashing-256" in str(raised.value)
