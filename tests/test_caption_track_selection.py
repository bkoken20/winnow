"""Ask for the original caption track, not a translation of it.

`--sub-langs` is a REGEX, documented as such: "en.*" matches "en" followed by anything. On a
real video that resolved to exactly two tracks:

    en-orig   English (Original)     <- the ASR track
    en        English                <- YouTube's auto-translation, into English

The same video offers 157 automatic caption languages; all but the original are machine
translations. So Winnow was downloading the original AND a translation of it -- verified
byte-identical, 206,817 bytes, same SHA -- and yt-dlp's maintainers name auto-translated
captions as the specific cause of the subtitle HTTP 429 that blocked this machine repeatedly.

The fix asks for `en-orig` first. Only if that writes nothing -- a video whose original
language is not English, or one with manual English subtitles instead of automatic ones --
does it fall back to `en`, which is then the translation the user actually wants.

The common case therefore becomes one request, one file, no translation endpoint touched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from winnow import acquire
from winnow.acquire import AcquisitionFailed


@pytest.fixture
def yt_dlp(monkeypatch):
    """A fake yt-dlp that writes only the tracks a given video 'has'."""
    calls = []

    def make(available: set[str]):
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            wanted = cmd[cmd.index("--sub-langs") + 1]
            dest = Path(cmd[cmd.index("-o") + 1]).parent
            dest.mkdir(parents=True, exist_ok=True)
            # yt-dlp treats each comma-separated entry as a regex.
            import re

            for track in sorted(available):
                if any(re.match(p, track) for p in wanted.split(",") if not p.startswith("-")):
                    (dest / f"video.{track}.vtt").write_text("WEBVTT\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
        monkeypatch.setattr(acquire.subprocess, "run", fake_run)
        return calls

    return make


def _langs(cmd) -> str:
    return cmd[cmd.index("--sub-langs") + 1]


def test_an_english_video_fetches_only_the_original_track(yt_dlp, tmp_path):
    calls = yt_dlp({"en-orig", "en", "fr", "de"})
    dest = tmp_path / "out"
    acquire.fetch("https://youtu.be/x", dest, announce=lambda *_: None)

    written = sorted(p.name for p in dest.glob("*.vtt"))
    assert written == ["video.en-orig.vtt"], (
        f"the original alone is wanted; a translation of it is a duplicate: {written}"
    )
    assert len(calls) == 1, "the common case must stay a single request"


def test_the_translation_endpoint_is_not_requested_when_an_original_exists(yt_dlp, tmp_path):
    calls = yt_dlp({"en-orig", "en"})
    acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=lambda *_: None)
    assert "en-orig" in _langs(calls[0])
    assert _langs(calls[0]) != "en.*", "the greedy wildcard is what pulled the translation"


def test_a_video_with_no_original_english_falls_back_to_the_translation(yt_dlp, tmp_path):
    """A non-English video: the translated track is the only English there is, and is wanted."""
    calls = yt_dlp({"tr-orig", "en", "fr"})
    dest = tmp_path / "out"
    acquire.fetch("https://youtu.be/x", dest, announce=lambda *_: None)

    written = sorted(p.name for p in dest.glob("*.vtt"))
    assert written == ["video.en.vtt"], f"the fallback must still get captions: {written}"
    assert len(calls) == 2, "fallback costs one extra request, and only in this case"


def test_the_fallback_is_announced(yt_dlp, tmp_path):
    """Nothing reaches the network without appearing on screen first -- including a retry."""
    yt_dlp({"tr-orig", "en"})
    said = []
    acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=said.append)
    assert sum(1 for line in said if line.startswith("running:")) == 2, (
        f"both requests must be printed, not just the first: {said!r}"
    )


def test_a_video_with_no_english_at_all_still_fails_clearly(yt_dlp, tmp_path):
    yt_dlp({"tr-orig", "fr"})
    with pytest.raises(AcquisitionFailed) as exc:
        acquire.fetch("https://youtu.be/x", tmp_path / "out", announce=lambda *_: None)
    assert "no captions" in str(exc.value).lower()


def test_an_explicit_language_choice_is_respected(yt_dlp, tmp_path):
    """`caption_languages` is the user's setting; the default must not override it."""
    calls = yt_dlp({"de-orig", "de", "en"})
    dest = tmp_path / "out"
    acquire.fetch("https://youtu.be/x", dest, languages="de-orig", announce=lambda *_: None)

    assert sorted(p.name for p in dest.glob("*.vtt")) == ["video.de-orig.vtt"]
    assert _langs(calls[0]) == "de-orig"
