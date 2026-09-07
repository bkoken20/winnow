"""The privacy statement must account for the one thing that reaches the network.

The README says: "`winnow status` states exactly what leaves your machine under your current
settings." So `egress_statement()` is the authority, not a summary of one.

It answered "FULLY LOCAL. Nothing leaves this machine" -- written when Winnow genuinely had
no network code outside Ollama. `winnow ingest <url>` now shells out to yt-dlp and contacts
a video site. The claim as written is false, and it is false in the direction that matters:
a user checking whether this tool phones anywhere is told, by the command documented as
authoritative, that it does not.

The README already had to be corrected for exactly this sentence. The code it defers to was
not.
"""
from __future__ import annotations

from pathlib import Path

from winnow.config import Config

ROOT = Path(__file__).resolve().parent.parent


def test_a_fully_local_statement_still_mentions_fetching():
    statement = Config().egress_statement()
    assert Config().is_fully_local, "default config should be local for models"
    lowered = statement.lower()
    assert "yt-dlp" in lowered or "fetch" in lowered or "url" in lowered, (
        "the statement claims nothing leaves the machine, but passing a URL to "
        f"`winnow ingest` contacts a video site. Statement was: {statement!r}"
    )


def test_it_does_not_claim_nothing_leaves_without_qualifying_it():
    """The exact sentence a reader would quote back."""
    statement = Config().egress_statement()
    if "nothing leaves this machine" in statement.lower():
        assert "except" in statement.lower() or "unless" in statement.lower(), (
            "an unqualified 'nothing leaves this machine' is false whenever a URL is "
            "passed to `winnow ingest`"
        )


def test_a_remote_host_is_still_reported_as_remote():
    """The fix must not weaken the case this statement exists for."""
    statement = Config(ollama_host="http://192.168.1.50:11434").egress_statement()
    assert statement.startswith("NOT FULLY LOCAL")
    assert "192.168.1.50" in statement


def test_the_readme_still_points_at_this_command_for_the_answer():
    """If the README stops deferring to `winnow status`, this test's premise is gone."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "winnow status" in readme
    assert "leaves your machine" in readme
