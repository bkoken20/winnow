"""`--config` must work wherever a person naturally puts it.

    winnow --config x.json ingest URL     worked
    winnow ingest URL --config x.json     error: unrecognized arguments: --config x.json

Both are the same intention, and argparse's message names the argument it rejected without
saying the only thing that helps: move it. The second form is the one people type, because
the subcommand is what they are thinking about and the configuration is an afterthought.

Reported by an external review.

The parser must also not FORGET a value it was given. `--config` on a subparser with an
ordinary default silently overwrites the top-level value with `None` when only the top-level
form is used -- so fixing the second spelling by hand is how you break the first.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"

# Every subcommand, with arguments that make it valid but do no work.
COMMANDS = [
    ["status"],
    ["packs"],
    ["rejudge"],
    ["index"],
    ["ingest", "talk.txt"],
]


def _config(tmp_path) -> Path:
    path = tmp_path / "elsewhere.json"
    path.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c[0])
def test_the_flag_is_accepted_after_the_subcommand(tmp_path, command):
    config = _config(tmp_path)
    parser = cli.build_parser()

    args = parser.parse_args([*command, "--config", str(config)])

    assert args.config == str(config), (
        "the flag was accepted in the position nobody types but not in the one they do"
    )


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c[0])
def test_the_flag_is_still_accepted_before_the_subcommand(tmp_path, command):
    """The guard: a subparser copy with an ordinary default overwrites this with None."""
    config = _config(tmp_path)
    parser = cli.build_parser()

    args = parser.parse_args(["--config", str(config), *command])

    assert args.config == str(config), (
        "adding the flag to the subparser made the documented spelling forget its value"
    )


def test_neither_position_leaves_it_unset(tmp_path):
    parser = cli.build_parser()
    args = parser.parse_args(["status"])
    assert args.config is None, "no flag given means no config path, not a missing attribute"


def test_the_later_spelling_wins_when_both_are_given(tmp_path):
    """Two positions, one value. Whichever is given, the answer must be a real path."""
    first = _config(tmp_path)
    second = tmp_path / "second.json"
    second.write_text("{}", encoding="utf-8")

    args = cli.build_parser().parse_args(
        ["--config", str(first), "status", "--config", str(second)]
    )

    assert args.config in (str(first), str(second)), f"got {args.config!r}"


def test_a_run_actually_reads_the_config_given_after_the_subcommand(tmp_path, capsys):
    """Parsing it is not the point; using it is."""
    config = _config(tmp_path)

    code = cli.main(["status", "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert code == 0, said
    assert str(tmp_path / "corpus.db") in said, (
        f"the flag parsed but the run used a different configuration: {said!r}"
    )
