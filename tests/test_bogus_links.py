"""A link that is nearly right must be told what is wrong with it.

`looks_like_url` requires an http/https scheme AND a host. Anything else falls through to
the path branch, so the commonest paste mistakes there are -- dropping the scheme, or
mistyping it -- produced:

    no such file or folder: youtu.be\\dQw4w9WgXcQ
    exit=2

Two faults in one line. It calls a URL a missing file, and it echoes back a string the user
never typed: `Path()` has flipped the forward slashes to backslashes, so the thing quoted at
them does not match the thing in their clipboard.

YouTube itself displays links without the scheme, so pasting `youtu.be/...` or
`www.youtube.com/watch?v=...` is not an exotic mistake. It is the default one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


@pytest.fixture
def config(tmp_path) -> Path:
    path = tmp_path / "winnow.json"
    path.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "c.db"),
            "cache_path": str(tmp_path / "cache"),
            "embed_backend": "hashing",
            "packs_root": str(PACKS_ROOT),
        }),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "link",
    [
        "youtu.be/dQw4w9WgXcQ",
        "www.youtube.com/watch?v=abc123",
        "youtube.com/watch?v=abc123",
    ],
)
def test_a_link_without_a_scheme_is_recognised_as_a_link(link, config, capsys):
    code = cli.main(["--config", str(config), "ingest", link])
    said = (capsys.readouterr().err + capsys.readouterr().out).lower()

    assert code == 2
    assert "no such file" not in said, f"a URL was reported as a missing file: {said!r}"
    assert "https://" in said, "say what to prefix it with"


def test_a_mistyped_scheme_says_so(config, capsys):
    code = cli.main(["--config", str(config), "ingest", "htps://youtu.be/abc123"])
    said = capsys.readouterr().err.lower()

    assert code == 2
    assert "scheme" in said or "https" in said, (
        f"'htps' is a typo for a scheme, not a folder name: {said!r}"
    )


def test_an_incomplete_url_is_not_reported_as_a_path(config, capsys):
    code = cli.main(["--config", str(config), "ingest", "https://"])
    said = capsys.readouterr().err.lower()

    assert code == 2
    assert "no such file" not in said, f"'https://' is not a filename: {said!r}"


def test_the_message_quotes_what_the_user_actually_typed(config, capsys):
    """`Path()` normalises separators, so the echo did not match the clipboard."""
    cli.main(["--config", str(config), "ingest", "youtu.be/dQw4w9WgXcQ"])
    said = capsys.readouterr().err

    assert "youtu.be/dQw4w9WgXcQ" in said, (
        f"the message must quote the original string, not a normalised path: {said!r}"
    )
    assert "youtu.be\\dQw4w9WgXcQ" not in said


def test_a_genuinely_missing_file_still_says_so(config, capsys, tmp_path):
    """The guard: ordinary path mistakes must keep their ordinary message."""
    code = cli.main(["--config", str(config), "ingest", str(tmp_path / "notes" / "talk.txt")])
    said = capsys.readouterr().err.lower()

    assert code == 2
    assert "no such file" in said
    assert "https://" not in said, "a filename is not a link; do not offer link advice"
