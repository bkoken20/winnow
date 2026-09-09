"""The offline test embedder produces meaningless similarity, and only one command said so.

`embed_backend: "hashing"` exists so the suite can run with no model server. Its vectors are
a hash of the text: two claims that say the same thing in different words score no closer
together than two unrelated ones. Every number it produces is noise.

`ingest` warns. Measured on the other three:

    status   exit 0   "embeddings    : nomic-embed-text via hashing"   (a config line)
    index    exit 0   no mention of hashing at all
    rejudge  exit 0   no mention of hashing at all

So the corpus can be BUILT entirely with it, and re-judged with it, without a word — and
`status`, the command whose job is to tell you the state of things, prints it as an ordinary
configuration value beside the model name, which reads as a setting rather than a problem.

The failure this allows is quiet: a corpus indexed with the hashing backend contains real
claims and useless vectors. Nothing about the claims looks wrong, and every verdict computed
against them is meaningless. `winnow status` is exactly where someone would look.

Reported by an external review.
"""
from __future__ import annotations

import json
from pathlib import Path

from winnow.config import Config
from winnow.pipeline import Pipeline
from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _offline(monkeypatch) -> None:
    """Keep `cli.main` off the network, the way tests/test_cli.py already does.

    The suite's whole point is that it runs with no model server, so a CLI test that goes
    through `Pipeline.build` has to swap the extractor's LLM on the way past.
    """
    from winnow.extract import Extractor

    real_build = Pipeline.build

    def build_with_stub(config):
        pipeline = real_build(config)
        pipeline.extractor = Extractor(
            llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
        )
        return pipeline

    monkeypatch.setattr(Pipeline, "build", staticmethod(build_with_stub))


def _config(tmp_path, corpus: Path, **overrides) -> Path:
    body = {
        "pack": "ai_tooling",
        "corpus_path": str(corpus),
        "embed_backend": "hashing",
        "packs_root": str(PACKS_ROOT),
        "index_extra_passes": [],
    }
    body.update(overrides)
    path = tmp_path / "winnow.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir(exist_ok=True)
    (folder / "a.md").write_text("throughput is bandwidth bound", encoding="utf-8")
    return folder


def _build(tmp_path, corpus: Path) -> None:
    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(corpus),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
            index_extra_passes=[],
        )
    )
    pipeline.extractor.llm = LineClaimsLLM()
    try:
        pipeline.index_notes_folder(_notes(tmp_path), accept_minutes=600)
    finally:
        pipeline.close()


def _warned(said: str) -> bool:
    """A warning, not a mention. The config line already contained the word 'hashing'."""
    lowered = said.lower()
    return "hashing" in lowered and any(
        phrase in lowered for phrase in ("mean nothing", "meaningless", "tests only")
    )


def test_status_calls_the_test_backend_what_it_is(tmp_path, capsys):
    corpus = tmp_path / "winnow.db"
    _build(tmp_path, corpus)
    capsys.readouterr()

    cli.main(["status", "--config", str(_config(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert _warned(said), (
        f"status printed the backend as an ordinary setting and never said the numbers "
        f"are meaningless: {said!r}"
    )


def test_index_says_so_before_building_a_corpus_of_noise(tmp_path, capsys, monkeypatch):
    corpus = tmp_path / "winnow.db"
    config = _config(tmp_path, corpus)
    _notes(tmp_path)

    _offline(monkeypatch)
    cli.main(["index", str(tmp_path / "notes"), "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert _warned(said), f"a whole corpus was built out of noise in silence: {said!r}"


def test_rejudge_says_so(tmp_path, capsys):
    corpus = tmp_path / "winnow.db"
    _build(tmp_path, corpus)
    capsys.readouterr()

    cli.main(["rejudge", "--config", str(_config(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert _warned(said), f"every verdict was recomputed from noise in silence: {said!r}"


def test_ingest_still_says_so(tmp_path, capsys, monkeypatch):
    """It already did. The warning must not move, only spread."""
    corpus = tmp_path / "winnow.db"
    _build(tmp_path, corpus)
    capsys.readouterr()

    talk = tmp_path / "talk.txt"
    talk.write_text("batching raises utilisation", encoding="utf-8")

    _offline(monkeypatch)
    cli.main(["ingest", str(talk), "--config", str(_config(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert _warned(said)


def test_a_real_backend_is_not_warned_about(tmp_path, capsys):
    """The mirror: a warning on every run is a warning nobody reads."""
    corpus = tmp_path / "winnow.db"
    config = _config(tmp_path, corpus, embed_backend="ollama")

    cli.main(["status", "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert not _warned(said), f"the real backend was warned about: {said!r}"
    assert "hashing" not in said.lower()
