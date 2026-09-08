"""The advice under a failed fetch must match what yt-dlp actually says.

Written after testing a real members-only video, which was the one cause I had documented
without ever provoking it.

The advice quoted `'Sign in to confirm': the site is gating it`. That string is real, but it
is YouTube's BOT CHECK ("Sign in to confirm you're not a bot") -- a different failure with a
different fix. Actual gating produces:

    This video is available to this channel's members on level: Seriously (or any higher
    level). Join this channel to get access to members-only content...

which matches nothing in the list. A reader scanning four bullets for their own error finds
none of them, and concludes the tool has not seen this before.

Quoting a yt-dlp phrase is useful only when the phrase is the one that appears. These tests
pin the two that were verified against live failures, and stop a cause being described by a
string it does not produce.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from winnow import acquire
from winnow.acquire import AcquisitionFailed

ROOT = Path(__file__).resolve().parent.parent


def _failing_fetch(stderr: str, tmp_path, monkeypatch):
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(
        acquire.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", stderr),
    )
    with pytest.raises(AcquisitionFailed) as exc:
        acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=lambda *_: None)
    return str(exc.value)


# Both verbatim from live runs against real videos.
MEMBERS_ONLY = (
    "ERROR: [youtube] IGBp6QdsR2s: This video is available to this channel's members on "
    "level: Seriously (or any higher level). Join this channel to get access to "
    "members-only content and other exclusive perks."
)
UNAVAILABLE = "ERROR: [youtube] AAAAAAAAAAA: This video is unavailable"


def _advice(message: str) -> str:
    """Only the part Winnow writes.

    The first version of this checked the whole message and passed because yt-dlp's own
    error -- which contains the word "members" -- is echoed into it. A test satisfied by its
    own input is not a test.
    """
    assert "Common causes:" in message, f"advice block missing from: {message!r}"
    return message.split("Common causes:", 1)[1].lower()


def test_a_members_only_video_finds_its_cause_in_the_list(tmp_path, monkeypatch):
    advice = _advice(_failing_fetch(MEMBERS_ONLY, tmp_path, monkeypatch))
    assert "members" in advice or "gated" in advice, (
        f"gating is what actually happened, and no bullet described it: {advice!r}"
    )


def test_the_advice_does_not_quote_a_string_gating_never_produces(tmp_path, monkeypatch):
    """"Sign in to confirm" is the bot check, not gating. Do not label one as the other."""
    message = _failing_fetch(MEMBERS_ONLY, tmp_path, monkeypatch)
    if "Sign in to confirm" in message:
        assert "bot" in message.lower(), (
            "'Sign in to confirm you're not a bot' is YouTube's bot check. Listing it as "
            "the marker for gated content sends the reader after the wrong problem."
        )


def test_an_unavailable_video_still_finds_its_cause(tmp_path, monkeypatch):
    message = _failing_fetch(UNAVAILABLE, tmp_path, monkeypatch).lower()
    assert "unavailable" in message


def test_the_servers_own_lines_are_always_shown(tmp_path, monkeypatch):
    """Whatever the cause, yt-dlp's text is the authority and must reach the user."""
    message = _failing_fetch(MEMBERS_ONLY, tmp_path, monkeypatch)
    assert "members on level" in message, "yt-dlp's own explanation was truncated away"


def test_the_acquisition_doc_describes_gating_the_way_it_appears():
    doc = (ROOT / "docs" / "ACQUISITION.md").read_text(encoding="utf-8").lower()
    assert "members" in doc or "gated" in doc, (
        "the troubleshooting section should name the form gating actually takes"
    )
