"""Nothing is sent to a model host before the user is told where it goes.

The README promises that Winnow says plainly what leaves the machine. `egress_statement()`
delivers on that -- and was printed by exactly one command, `status`. `index`, `ingest` and
`rejudge`, the three that actually transmit transcripts, notes and claims, said nothing at
all. A user who set `ollama_host` to another machine, or who never ran `status`, got no
disclosure on any path that sends data.

Reported as W-003 by an external review.

The root cause is a design rule this project already writes down: if correctness depends on a
caller remembering, the design is wrong. One command remembered. So the announcement belongs
where every processing path must pass -- `Pipeline.build()` -- rather than being repeated in
each command and forgotten by the next one added.

These tests assert ORDER, not presence: the disclosure must reach the user BEFORE the first
request leaves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class RecordingEmbedder:
    """Notes when the first request would have gone out."""

    name = "nomic-embed-text"
    backend = "ollama"

    def __init__(self, log: list[str]):
        self.log = log

    def embed(self, text: str) -> list[float]:
        self.log.append("REQUEST")
        return [1.0, 0.0, 0.0]


def _config(tmp_path, **overrides) -> Config:
    base = dict(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        index_extra_passes=[],
        ingest_extra_passes=[],
    )
    base.update(overrides)
    return Config(**base)


def test_building_a_pipeline_announces_where_data_goes(tmp_path, capsys):
    Pipeline.build(_config(tmp_path)).close()
    said = capsys.readouterr()
    disclosure = said.out + said.err

    assert "localhost:11434" in disclosure, (
        f"the actual destination must be named, not merely a declared location: {disclosure!r}"
    )


def test_a_remote_host_is_disclosed_as_remote(tmp_path, capsys):
    Pipeline.build(_config(tmp_path, ollama_host="http://192.168.1.50:11434")).close()
    disclosure = "".join(capsys.readouterr())

    assert "NOT FULLY LOCAL" in disclosure
    assert "192.168.1.50" in disclosure, (
        "the disclosure must name where the data actually goes, taken from ollama_host "
        "rather than from the declarative judge_location"
    )


def test_the_disclosure_precedes_the_first_request(tmp_path, capsys):
    """Order is the guarantee. A disclosure printed afterwards is not one."""
    log: list[str] = []

    pipeline = Pipeline.build(_config(tmp_path, ollama_host="http://192.168.1.50:11434"))
    if "".join(capsys.readouterr()):
        log.append("DISCLOSED")

    pipeline.judge.embedder = RecordingEmbedder(log)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("a specific claim about throughput", encoding="utf-8")
    pipeline.extractor.llm = type(
        "L", (), {"generate": lambda self, m, p, *, num_ctx, as_json=False:
                  json.dumps({"claims": [{"claim": "a specific claim about throughput"}]})}
    )()
    try:
        pipeline.index_note(notes / "a.md")
    finally:
        pipeline.close()

    assert log, "nothing happened"
    assert log[0] == "DISCLOSED", (
        f"the first request went out before the user was told where: {log}"
    )


@pytest.mark.parametrize("command", ["index", "ingest", "rejudge"])
def test_every_processing_command_discloses(tmp_path, capsys, command):
    """The three that transmit. `status` already did; these did not."""
    from winnow import cli

    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "c.db"),
            "embed_backend": "hashing",
            "packs_root": str(PACKS_ROOT),
            "ollama_host": "http://192.168.1.50:11434",
            "index_extra_passes": [],
            "ingest_extra_passes": [],
        }),
        encoding="utf-8",
    )
    material = tmp_path / "material"
    material.mkdir()
    (material / "transcript.txt").write_text("a claim about throughput", encoding="utf-8")
    (material / "a.md").write_text("a claim about throughput", encoding="utf-8")

    argv = ["--config", str(config), command]
    if command in ("index", "ingest"):
        argv.append(str(material))

    from winnow import pipeline as pipeline_module

    original = pipeline_module.Pipeline.build

    def build(cfg):
        built = original(cfg)
        built.extractor.llm = type(
            "L", (), {"generate": lambda self, m, p, *, num_ctx, as_json=False:
                      json.dumps({"claims": []})}
        )()
        return built

    pipeline_module.Pipeline.build = staticmethod(build)
    try:
        cli.main(argv)
    finally:
        pipeline_module.Pipeline.build = staticmethod(original)

    disclosure = "".join(capsys.readouterr())
    assert "192.168.1.50" in disclosure, (
        f"`winnow {command}` sends data to a remote host and disclosed nothing"
    )
