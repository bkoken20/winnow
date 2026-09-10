"""`index` and `rejudge` never said what they cost, so their projection was uncheckable.

Both are gated commands: they measure one unit, project the whole run, and refuse it unless
you accept the figure. `index` then prints that projection a second time when the run is
over --

    measured 3.62s for 7.3 KB (2.0 KB/s); 4 files totalling 0.0 MB = about 24 seconds
    indexed 4 files -> 9 claims stored

-- and there is nothing beside it to compare against. The tool asks you to accept an
estimate, and then never tells you whether the estimate was any good. A projection you
cannot check is a number you have to take on faith, which is exactly the standing this
project does not grant its own figures elsewhere: `experiments/MEASUREMENTS.json` records
projection accuracy at 0.97x-1.19x of actual, measured deliberately, once. Every ordinary
run since has thrown that comparison away.

`ingest` already reports its elapsed time. This is the same fix at the two call sites that
were left out.

Asserted as a PROPERTY over every gated command rather than one test per command, because
"the reasoning was applied to the line that motivated it and to nothing else" is how three
earlier defects in this project happened -- most recently the flush on the yt-dlp
announcement that was never carried to the two lines above it. A command that grows an
`--accept-minutes` flag tomorrow is covered by this the day it appears.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from winnow import cli
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"

# What a duration looks like, in the one format `human_seconds` produces.
A_DURATION = r"(under a second|\d+(\.\d+)? (seconds?|minutes?|hours?))"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _offline(monkeypatch) -> None:
    from winnow.extract import Extractor

    real_build = Pipeline.build

    def build_with_stub(config):
        pipeline = real_build(config)
        pipeline.extractor = Extractor(
            llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
        )
        return pipeline

    monkeypatch.setattr(Pipeline, "build", staticmethod(build_with_stub))


def _config_file(tmp_path) -> Path:
    path = tmp_path / "winnow.json"
    path.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
                "index_extra_passes": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir(parents=True)
    for i in range(4):
        (folder / f"note{i}.md").write_text(
            "\n".join(
                f"Note {i} sentence {j} reports a throughput of {i * 10 + j} percent."
                for j in range(1 + i * 2)
            ),
            encoding="utf-8",
        )
    return folder


def _gated_commands() -> list[str]:
    """Every subcommand that offers --accept-minutes: read from the parser, not listed.

    A hand-written list is a list of the commands that existed when it was written.
    """
    parser = cli.build_parser()
    subparsers = [
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    ]
    assert subparsers, "no subcommands found; this test needs rewriting"

    gated = []
    for name, sub in subparsers[0].choices.items():
        flags = {opt for action in sub._actions for opt in action.option_strings}
        if "--accept-minutes" in flags:
            gated.append(name)
    return sorted(gated)


def test_the_gated_commands_are_the_ones_expected():
    """A guard on the guard: if this list changes, the tests below must cover the change."""
    assert _gated_commands() == ["index", "rejudge"], (
        "a command gained or lost --accept-minutes; the cost report must follow it"
    )


# -- the property -------------------------------------------------------------------


def test_index_says_what_it_cost(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    cli.main(["index", str(_notes(tmp_path)), "--config", str(_config_file(tmp_path)),
              "--accept-minutes", "600"])
    out = capsys.readouterr().out

    summary = next(ln for ln in out.splitlines() if "claims stored" in ln)
    assert re.search(rf"\bin {A_DURATION}\b", summary), (
        f"the run ended without saying what it cost: {summary!r}"
    )


def test_rejudge_says_what_it_cost(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    config = _config_file(tmp_path)
    cli.main(["index", str(_notes(tmp_path)), "--config", str(config),
              "--accept-minutes", "600"])
    capsys.readouterr()

    cli.main(["rejudge", "--config", str(config), "--accept-minutes", "600"])
    out = capsys.readouterr().out

    summary = next(ln for ln in out.splitlines() if "re-judged" in ln)
    assert re.search(rf"\bin {A_DURATION}\b", summary), (
        f"the run ended without saying what it cost: {summary!r}"
    )


def test_the_projection_and_the_actual_are_readable_together(tmp_path, capsys, monkeypatch):
    """The point of the elapsed figure: the estimate you accepted becomes checkable.

    Both numbers, in the same units, within a couple of lines of each other -- so a
    projection that is out by a factor is visible rather than something you would have to
    time yourself to discover.
    """
    _offline(monkeypatch)
    cli.main(["index", str(_notes(tmp_path)), "--config", str(_config_file(tmp_path)),
              "--accept-minutes", "600"])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]

    projected = next(i for i, ln in enumerate(lines) if "= about " in ln)
    actual = next(i for i, ln in enumerate(lines) if "claims stored" in ln)
    assert actual - projected == 1, (
        f"the projection and what it cost should read together: {lines}"
    )
    assert re.search(rf"= about {A_DURATION}", lines[projected]), lines[projected]


def test_the_elapsed_figure_is_the_shared_formatter(tmp_path, capsys, monkeypatch):
    """One way of writing a duration, so a projection and an outcome are comparable.

    A projection reading "about 24 seconds" beside an outcome reading "0:03:31" makes the
    reader do a conversion before they can tell the two apart.
    """
    _offline(monkeypatch)

    # A known duration, so this asserts a VALUE rather than the shape the regex above
    # already guarantees. The first reading is the clock cmd_index starts; every later one
    # is 150 seconds on, which also leaves time_one measuring a zero-cost unit.
    #
    # The previous version extracted the figure WITH `A_DURATION` and then asserted it
    # matched `A_DURATION`, which is true by construction. It could not fail.
    readings = {"n": 0}

    def clock():
        readings["n"] += 1
        return 0.0 if readings["n"] == 1 else 150.0

    monkeypatch.setattr(cli.time, "perf_counter", clock)

    cli.main(["index", str(_notes(tmp_path)), "--config", str(_config_file(tmp_path)),
              "--accept-minutes", "600"])
    out = capsys.readouterr().out

    summary = next(ln for ln in out.splitlines() if "claims stored" in ln)
    assert "in 2.5 minutes" in summary, (
        "150 seconds is '2.5 minutes' the way this project writes every other duration; a "
        "raw float or an H:MM:SS would make the reader convert before they could compare "
        f"it with the projection printed directly above: {summary!r}"
    )


def test_an_empty_rejudge_still_reports(tmp_path, capsys, monkeypatch):
    """Nothing to do is still a run the user waited through."""
    _offline(monkeypatch)
    config = _config_file(tmp_path)

    cli.main(["rejudge", "--config", str(config)])
    out = capsys.readouterr().out

    summary = next((ln for ln in out.splitlines() if "re-judged" in ln), None)
    assert summary is not None, out
    assert re.search(rf"\bin {A_DURATION}\b", summary), summary
