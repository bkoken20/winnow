"""The caption fallback must ask for captions, not for the video a second time.

When a video has no original-English track, `fetch` runs yt-dlp again for `en` -- the machine
translation. It passed `with_video` through unchanged, so with `--with-video` the second call
carried the video format selector and no `--skip-download`, asking for hundreds of megabytes
that the first call had already fetched.

The fallback only exists because the CAPTIONS were missing. The media, if it was wanted, is
already on disk: the fallback is reached only when the first call SUCCEEDED and simply wrote
no subtitles.

Reported by an external review.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from winnow import acquire


@pytest.fixture
def yt_dlp(monkeypatch):
    """A fake yt-dlp with no original-English track, recording every command."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        dest = Path(cmd[cmd.index("-o") + 1]).parent
        dest.mkdir(parents=True, exist_ok=True)
        wanted = cmd[cmd.index("--sub-langs") + 1]
        # Video is fetched whenever the download was not skipped.
        if "--skip-download" not in cmd:
            (dest / "video.mp4").write_bytes(b"\x00" * 16)
        # Only the translated track exists.
        if wanted == acquire.CAPTION_TRANSLATION_FALLBACK:
            (dest / "video.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(acquire.subprocess, "run", fake_run)
    return calls


def test_the_fallback_asks_for_captions_only(yt_dlp, tmp_path):
    acquire.fetch("https://youtu.be/x", tmp_path / "out",
                  with_video=True, announce=lambda *_: None)

    assert len(yt_dlp) == 2, f"expected an original attempt and a fallback: {len(yt_dlp)}"
    first, second = yt_dlp

    assert "--skip-download" not in first, "guard: the first call should honour --with-video"
    assert "--skip-download" in second, (
        "the fallback re-ran with the video flags, asking for a download the first call "
        f"already made: {second}"
    )


def test_the_fallback_carries_no_video_format_selector(yt_dlp, tmp_path):
    acquire.fetch("https://youtu.be/x", tmp_path / "out",
                  with_video=True, announce=lambda *_: None)
    second = yt_dlp[1]

    for flag in acquire.VIDEO_ARGS:
        assert flag not in second, (
            f"the fallback still selects a video format ({flag!r}); the media is already on "
            "disk from the first call"
        )


def test_the_video_is_fetched_once(yt_dlp, tmp_path):
    dest = tmp_path / "out"
    acquire.fetch("https://youtu.be/x", dest, with_video=True, announce=lambda *_: None)

    downloads = sum(1 for cmd in yt_dlp if "--skip-download" not in cmd)
    assert downloads == 1, f"the video was requested {downloads} times"
    assert (dest / "video.mp4").exists(), "and it must still be there"
    assert (dest / "video.en.vtt").exists(), "along with the captions the fallback found"


def test_a_captions_only_run_is_unaffected(yt_dlp, tmp_path):
    """The guard: the common path has no video in it either way."""
    acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=lambda *_: None)

    assert len(yt_dlp) == 2
    assert all("--skip-download" in cmd for cmd in yt_dlp)
