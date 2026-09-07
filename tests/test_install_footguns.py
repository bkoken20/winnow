"""Two things a stranger hits in the first minute, found by actually installing it.

`pip install .` -- without the `-e` the README specifies -- installs the `winnow` package but
not `packs/`, which is not inside it. Every command then fails to find a pack, and `winnow
packs` says "no packs found", which reads as "this project ships no packs" rather than "your
install is missing them". The tool is unusable and nothing says why.

And `winnow --help`, the most-read string in the tool, still described it as "Judge new
material against what you already know" -- the framing dropped from the README and
pyproject.toml when it learned to take URLs.

Neither is visible from reading the source. Both took one real install to find.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from winnow import cli, packs

ROOT = Path(__file__).resolve().parent.parent


def test_a_missing_packs_directory_says_what_to_do(tmp_path, capsys, monkeypatch):
    """"no packs found" is a description of the symptom, not of the cause."""
    monkeypatch.setattr(packs, "packs_root", lambda explicit=None: tmp_path / "absent")
    monkeypatch.setattr(cli, "available_packs", lambda root=None: [])

    code = cli.main(["--config", str(tmp_path / "winnow.json"), "packs"])
    output = capsys.readouterr()
    said = (output.out + output.err).lower()

    assert code != 0, "a tool that cannot find its packs has not succeeded"
    assert "-e" in said or "editable" in said, (
        "the message must name the cause: packs live beside the package, not inside it, so "
        f"a non-editable `pip install .` leaves them behind. Said: {said!r}"
    )


def test_the_cli_description_matches_the_project_description():
    """`winnow --help` is the most-read string in the tool; it must not be the old pitch."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^description = "([^"]+)"', pyproject, re.MULTILINE).group(1)

    parser_description = cli.build_parser().description or ""

    assert "youtube" in parser_description.lower(), (
        f"`winnow --help` describes the tool as {parser_description!r}, which predates it "
        "taking URLs at all"
    )
    # Not required to be identical -- one is a sentence, one is a help line -- but they must
    # not describe two different tools.
    assert "youtube" in declared.lower()


@pytest.mark.parametrize("phrase", ["Judge new material against what you already know."])
def test_the_superseded_pitch_is_gone_from_user_facing_strings(phrase):
    """It survived in two places after the README was reframed. Check them together."""
    offenders = []
    for rel in ("pyproject.toml", "winnow/cli.py", "winnow/__init__.py", "README.md"):
        if phrase in (ROOT / rel).read_text(encoding="utf-8"):
            offenders.append(rel)
    assert not offenders, f"the pre-URL pitch survives in: {offenders}"
