"""Changing the embedding model must not silently blind the corpus.

Vectors from two models are not comparable, and `similarity_search` skips mismatched
dimensions outright -- so a corpus built with one model is *entirely invisible* to another.
Nothing warned: every claim came back `new` against a corpus that might hold ten thousand
of them, and the tool reported that with full confidence.

It now refuses. A confident wrong answer is worse than a stop, which is the same reasoning
that makes a thin corpus report `unknown` rather than `new`.
"""

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.extract import Extractor
from winnow.pipeline import CorpusEmbeddingMismatch, Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class OneClaimLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        return json.dumps({"claims": [{"claim": "prefix caching cuts time to first token"}]})


def config_for(tmp_path, corpus="corpus.db", **overrides) -> Config:
    settings = {
        "pack": "ai_tooling",
        "corpus_path": str(tmp_path / corpus),
        "packs_root": str(PACKS_ROOT),
        "embed_backend": "hashing",
    }
    settings.update(overrides)  # callers may override any default, including the backend
    return Config(**settings)


def seed_corpus(config) -> None:
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(
        llm=OneClaimLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    note = Path(config.corpus_path).parent / "note.md"
    note.write_text("anything", encoding="utf-8")
    pipeline.index_note(note)
    pipeline.close()


def test_a_corpus_built_by_another_model_is_refused(tmp_path):
    seed_corpus(config_for(tmp_path))

    switched = config_for(tmp_path, embed_backend="ollama", embed_model="nomic-embed-text")
    with pytest.raises(CorpusEmbeddingMismatch) as exc:
        Pipeline.build(switched)

    message = str(exc.value)
    assert "hashing" in message, "the message must name the model the corpus was built with"
    assert "nomic-embed-text" in message, "and the model now configured"
    assert "re-index" in message, "and what to do about it"


def test_the_same_model_is_not_refused(tmp_path):
    """The guard must not fire on ordinary use."""
    config = config_for(tmp_path)
    seed_corpus(config)
    Pipeline.build(config).close()


def test_a_fresh_corpus_accepts_any_model(tmp_path):
    """Switching models is fine -- it is switching them UNDER a corpus that is not."""
    seed_corpus(config_for(tmp_path))
    fresh = config_for(tmp_path, corpus="other.db", embed_backend="ollama",
                       embed_model="nomic-embed-text")
    Pipeline.build(fresh).close()


def test_an_empty_corpus_accepts_any_model(tmp_path):
    Pipeline.build(config_for(tmp_path, embed_backend="ollama",
                              embed_model="nomic-embed-text")).close()


def test_the_guard_reports_every_foreign_model(tmp_path):
    """A corpus can hold more than one, if it was written before this check existed."""
    from winnow.models import Claim, Source
    from winnow.store import Store

    config = config_for(tmp_path)
    store = Store(config.corpus_path)
    store.add_source(Source(id="s", pack="ai_tooling", kind="note", path="/x"))
    for i, model in enumerate(["model-a", "model-b"]):
        store.add_claim(
            Claim(id=f"c{i}", pack="ai_tooling", source_id="s", text=f"claim {i}"),
            [0.1] * 8,
            model,
        )
    store.close()

    with pytest.raises(CorpusEmbeddingMismatch) as exc:
        Pipeline.build(config)
    assert "model-a" in str(exc.value) and "model-b" in str(exc.value)


def test_the_cli_reports_the_mismatch_cleanly(tmp_path, capsys):
    from winnow import cli

    seed_corpus(config_for(tmp_path))
    switched = tmp_path / "switched.json"
    config_for(tmp_path, embed_backend="ollama", embed_model="nomic-embed-text").save(switched)

    cli.main(["--config", str(switched), "status"])
    out = capsys.readouterr()
    combined = out.out + out.err

    assert "Traceback" not in combined
    assert "UNUSABLE" in combined, (
        "status is where someone looks when results seem wrong; it must say the corpus "
        "cannot be used, not report it as merely small"
    )
    assert "hashing" in combined and "nomic-embed-text" in combined
