"""The fetch command must not provoke the rate limit it warns about.

yt-dlp's guidance names `--sleep-requests 2` as the flag that addresses the cause of a
YouTube 429 -- pacing the metadata requests rather than firing them back to back. Winnow's
own docs told users to add it for bulk fetches while Winnow's own command did not use it.

A block lasts minutes for a light trip and several hours for a sustained one, with no way to
query the remaining time and no appeal, so the cost of provoking one is asymmetric: two
seconds against hours.

NOT changed here, deliberately: `--sub-langs en.*`. That wildcard is very likely the real
culprit -- it pulled `en-orig` AND `en` on a real video, byte-identical, and the second comes
via the auto-translation endpoint that maintainers name as the specific cause of the subtitle
429. Changing it needs a live fetch to verify, and the machine is throttled. See
docs/ACQUISITION.md; it is written down rather than guessed at.
"""
from __future__ import annotations

import subprocess

import pytest

from winnow import acquire


@pytest.fixture
def recorded(monkeypatch):
    """Capture the command without running anything."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        dest = cmd[cmd.index("-o") + 1]
        from pathlib import Path

        folder = Path(dest).parent
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(acquire.subprocess, "run", fake_run)
    return seen


def test_requests_are_paced(recorded, tmp_path):
    acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=lambda *_: None)
    cmd = recorded["cmd"]

    assert "--sleep-requests" in cmd, (
        "yt-dlp names this as the flag that addresses the cause of a 429, and Winnow's own "
        "docs recommend it while its own command did not use it"
    )
    value = float(cmd[cmd.index("--sleep-requests") + 1])
    assert value >= 1, f"a sub-second pause is not pacing: {value}"


def test_pacing_does_not_replace_the_captions_only_default(recorded, tmp_path):
    """The guard: pacing must not disturb what is actually requested."""
    acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=lambda *_: None)
    cmd = recorded["cmd"]

    assert "--skip-download" in cmd, "captions only is still the default"
    assert "--sub-format" in cmd and "vtt" in cmd


def test_the_announced_command_shows_the_pacing(recorded, tmp_path):
    """Nothing reaches the network without appearing on screen -- including the pacing."""
    said = []
    acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=said.append)
    assert any("--sleep-requests" in line for line in said), (
        f"the printed command must be the command that runs: {said!r}"
    )
