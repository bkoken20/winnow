"""A bare dotted name is ambiguous, and Winnow guessed -- wrongly, and confidently.

Measured:

    winnow ingest data.backup     'data.backup' looks like a link with no scheme.
                                  Try https://data.backup
    winnow ingest notes.tar.gz    Try https://notes.tar.gz
    winnow ingest report.docx     Try https://report.docx
    winnow ingest archive.zip     Try https://archive.zip

None of those is a link, and the advice is nonsense for all four. This was fixed once by
listing the extensions Winnow can read, and `winnow/acquire.py` carries the note explaining
why that was necessary — but `.backup`, `.docx` and `.zip` are not on the list and never
will be, because the list is of things Winnow READS. The class is "a filename", and no list
of extensions describes it.

`.zip` is a real top-level domain, so no rule can tell `archive.zip` the file from
`archive.zip` the host. That is the point: **it is genuinely ambiguous, so the answer must
be too.**

What is NOT ambiguous is a host with a path after it — `youtu.be/VIDEO_ID`,
`www.youtube.com/watch?v=x` — which is what a link pasted without its scheme actually looks
like, because YouTube always shows one. That keeps the confident advice.

Reported by an external review.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow import cli
from winnow.acquire import why_not_a_url

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


def _config(tmp_path) -> Path:
    path = tmp_path / "winnow.json"
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


@pytest.mark.parametrize(
    "name",
    ["data.backup", "notes.tar.gz", "report.docx", "archive.zip", "photo.jpeg",
     "2024.figures.xlsx"],
)
def test_a_bare_dotted_name_is_not_declared_a_link(name):
    """No separator, so nothing says host. `why_not_a_url` must not claim it is one."""
    assert why_not_a_url(name) is None, (
        f"{name!r} is a filename and was answered with link advice: {why_not_a_url(name)}"
    )


@pytest.mark.parametrize(
    "link",
    [
        "youtu.be/IGBp6QdsR2s",
        "www.youtube.com/watch?v=abc",
        "youtube.com/watch?v=abc",
        "vimeo.com/12345",
    ],
)
def test_a_host_with_a_path_is_still_recognised(link):
    """The case this advice exists for: YouTube shows links without their scheme."""
    said = why_not_a_url(link)

    assert said is not None, f"{link!r} is a pasted link and got no advice"
    assert f"https://{link}" in said


@pytest.mark.parametrize("name", ["data.backup", "archive.zip", "notes.tar.gz"])
def test_the_command_reports_a_missing_file_and_offers_the_other_reading(
    tmp_path, capsys, name
):
    """Ambiguous input, so say both -- leading with the likelier one."""
    code = cli.main(["ingest", name, "--config", str(_config(tmp_path))])
    said = "".join(capsys.readouterr())

    assert code == 2, f"bad input is 2: {said!r}"
    assert name in said, f"quote back what they typed: {said!r}"
    lowered = said.lower()
    assert "no such file" in lowered or "not found" in lowered, (
        f"lead with the file reading, which is the likelier one: {said!r}"
    )
    assert "https://" in said, (
        f"and offer the other reading rather than hiding it: {said!r}"
    )


def test_a_pasted_link_still_gets_the_link_message(tmp_path, capsys):
    code = cli.main(["ingest", "youtu.be/IGBp6QdsR2s", "--config", str(_config(tmp_path))])
    said = "".join(capsys.readouterr())

    assert code == 2
    assert "https://youtu.be/IGBp6QdsR2s" in said
    assert "no such file" not in said.lower(), (
        f"a link is not a missing file, and saying so buries the advice: {said!r}"
    )


def test_the_message_quotes_what_was_typed(tmp_path, capsys):
    """Found by walking the failure path, not by running it.

    `Path()` normalises separators, so on Windows `notes/talk.txt` came back as
    `notes\talk.txt` -- a string the user cannot find on their own command line.
    `why_not_a_url`'s docstring names this as part of why it exists, and the line
    immediately after it still did it.
    """
    typed = "notes/talk.txt"
    code = cli.main(["ingest", typed, "--config", str(_config(tmp_path))])
    said = "".join(capsys.readouterr())

    assert code == 2
    assert typed in said, f"the message quoted something else: {said!r}"


def test_an_ordinary_relative_path_is_untouched(tmp_path, capsys):
    """The guard from the previous round of this: `notes/talk.txt` is not a host."""
    assert why_not_a_url("notes/talk.txt") is None
    assert why_not_a_url("./notes") is None
    assert why_not_a_url("talk.txt") is None


def test_a_file_that_exists_is_just_read(tmp_path, capsys):
    """The other guard: none of this may touch input that is simply correct."""
    talk = tmp_path / "talk.backup"
    talk.write_text("a specific claim about throughput", encoding="utf-8")

    code = cli.main(["ingest", str(talk), "--config", str(_config(tmp_path))])
    said = "".join(capsys.readouterr())

    assert "https://" not in said.replace("http://localhost", ""), (
        f"an existing file was offered link advice: {said!r}"
    )
    assert code in (0, 2), said
