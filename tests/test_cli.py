"""CLI-level tests.

These exist because `winnow ingest` crashed on real use while all 82 tests below it were
green. The command closes the pipeline in a `finally` and then formats its output; the
formatting code was reading claim text back out of the database, which by then was closed.

Nothing that only calls `Pipeline.ingest()` directly can see that. The command itself has
to be run.
"""

import json
from pathlib import Path

import pytest

from winnow import cli
from winnow.config import Config
from winnow.extract import Extractor
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class OneClaimPerLineLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        claims = [
            {"claim": line.strip(), "kind": "observation"}
            for line in body.splitlines()
            if line.strip()
        ][:5]
        return json.dumps({"claims": claims})


@pytest.fixture
def offline_cli(tmp_path, monkeypatch):
    """Wire the CLI to the offline embedder and a fake extraction model."""
    config_path = tmp_path / "winnow.json"
    Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
    ).save(config_path)

    real_build = Pipeline.build

    def build_with_fake_model(config):
        pipeline = real_build(config)
        pipeline.extractor = Extractor(
            llm=OneClaimPerLineLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
        )
        return pipeline

    monkeypatch.setattr(Pipeline, "build", staticmethod(build_with_fake_model))
    return config_path


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


def seed_notes(folder: Path, count: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (folder / f"n{i:02d}.md").write_text(
            _note_text(i), encoding="utf-8"
        )
    return folder


def test_ingest_command_prints_verdicts_without_touching_a_closed_db(
    offline_cli, tmp_path, capsys
):
    """The regression: reading claim text after `finally: pipeline.close()`."""
    notes = seed_notes(tmp_path / "notes", 30)
    assert cli.main(["--config", str(offline_cli), "index", str(notes)]) == 0

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text(
        _note_text(7) + "\n"
        "a wholly unrelated assertion concerning maritime navigation\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["--config", str(offline_cli), "ingest", str(material)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "2 claims extracted" in output
    # The claim text must actually appear -- not an id, and not a crash.
    assert _note_text(7)[:20] in output
    assert "maritime navigation" in output


def test_ingest_warns_when_verdicts_used_the_test_embedder(offline_cli, tmp_path, capsys):
    notes = seed_notes(tmp_path / "notes", 30)
    cli.main(["--config", str(offline_cli), "index", str(notes)])
    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text("some assertion", encoding="utf-8")

    cli.main(["--config", str(offline_cli), "ingest", str(material)])
    assert "mean nothing" in capsys.readouterr().out


def test_ingest_missing_transcript_exits_nonzero(offline_cli, tmp_path, capsys):
    material = tmp_path / "talk"
    material.mkdir()
    (material / "video.mp4").write_bytes(b"\x00")
    assert cli.main(["--config", str(offline_cli), "ingest", str(material)]) == 2
    assert "ACQUISITION.md" in capsys.readouterr().err


def test_index_refuses_a_long_run_and_exits_nonzero(offline_cli, tmp_path, monkeypatch, capsys):
    from winnow import cost

    # Force a projection far above the gate threshold.
    monkeypatch.setattr(
        cost.Projection, "total_seconds", property(lambda self: 10_000.0)
    )
    notes = seed_notes(tmp_path / "notes", 5)
    assert cli.main(["--config", str(offline_cli), "index", str(notes)]) == 3
    assert "accept-minutes" in capsys.readouterr().err


def test_status_reports_privacy_and_corpus(offline_cli, capsys):
    assert cli.main(["--config", str(offline_cli), "status"]) == 0
    output = capsys.readouterr().out
    assert "FULLY LOCAL" in output
    assert "0 claims" in output
    assert "below the" in output  # the coverage warning


def test_packs_lists_the_shipped_pack(offline_cli, capsys):
    assert cli.main(["--config", str(offline_cli), "packs"]) == 0
    assert "ai_tooling" in capsys.readouterr().out


def test_rejudge_runs_over_the_corpus(offline_cli, tmp_path, capsys):
    notes = seed_notes(tmp_path / "notes", 30)
    cli.main(["--config", str(offline_cli), "index", str(notes)])
    assert cli.main(["--config", str(offline_cli), "rejudge"]) == 0
    assert "re-judged 30 claims" in capsys.readouterr().out
