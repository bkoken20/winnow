"""ffmpeg could run forever, and a timeout would have escaped as a traceback.

`ffmpeg_available()` already passes `timeout=20` to its version probe. `extract_frames` — the
call that actually decodes a video — passes none. A truncated download, a malformed container
or a stream ffmpeg cannot make sense of leaves it spinning, and Winnow waits with no output
and no end.

This is the same defect as the yt-dlp one fixed earlier today, in the module next door. The
fix there did not travel, because I looked at the file the review named rather than at the
class of call.

The consequence differs, though, and that shapes the fix. Frames are the OPTIONAL half:
`describe_frames` documents that it returns an empty string whenever frames are unavailable
for any reason, so that "an ingest whose transcript is already in hand must not fail because
the optional half is missing." A timeout belongs in that set — but it must be SAID, because a
silent "no frames" is indistinguishable from a video that had none.

`describe_frames` currently catches `FFmpegMissing` alone, so a `TimeoutExpired` would escape
`cli._run` as a traceback.

Reported by an external review as a low-priority hardening item.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from winnow import media
from winnow.config import Config
from winnow.media import FramesTimedOut, extract_frames

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


def test_ffmpeg_is_given_a_time_limit(tmp_path, monkeypatch):
    seen = {}

    def record(command, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media.subprocess, "run", record)

    extract_frames(tmp_path / "video.mp4", tmp_path / "out")

    assert seen["timeout"], "ffmpeg was run with no time limit at all"


def test_the_limit_is_configurable(tmp_path, monkeypatch):
    seen = {}

    def record(command, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media.subprocess, "run", record)

    extract_frames(tmp_path / "video.mp4", tmp_path / "out", timeout_seconds=11)

    assert seen["timeout"] == 11


def test_the_default_comes_from_the_configuration():
    assert Config().frame_timeout_seconds > 0
    assert Config(frame_timeout_seconds=42).frame_timeout_seconds == 42


def test_there_is_only_one_default():
    """The lesson from the fetch timeout: two constants that agree until one is edited."""
    from winnow.config import DEFAULT_FRAME_TIMEOUT

    assert media.DEFAULT_FRAME_TIMEOUT is DEFAULT_FRAME_TIMEOUT
    assert Config().frame_timeout_seconds == DEFAULT_FRAME_TIMEOUT


def test_a_hung_ffmpeg_raises_something_the_caller_understands(tmp_path, monkeypatch):
    """Not a bare TimeoutExpired: `describe_frames` has to be able to catch it by name."""

    def hangs(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media.subprocess, "run", hangs)

    with pytest.raises(FramesTimedOut) as raised:
        extract_frames(tmp_path / "video.mp4", tmp_path / "out", timeout_seconds=3)

    said = str(raised.value)
    assert "frame_timeout_seconds" in said, (
        f"name the setting that changes it, or the message is a dead end: {said!r}"
    )


def test_an_ingest_survives_a_hung_ffmpeg_and_says_so(tmp_path, capsys, monkeypatch):
    """Frames are the optional half. Losing them must not lose the transcript.

    But it must not be silent either: "no frames" from a timeout looks exactly like "no
    frames" from a video that had none, and only one of those is worth knowing about.
    """
    from winnow.pipeline import Pipeline

    def hangs(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media.subprocess, "run", hangs)
    monkeypatch.setattr("winnow.pipeline.find_media_file", lambda target: tmp_path / "v.mp4")

    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text("throughput is bandwidth bound", encoding="utf-8")

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(tmp_path / "corpus.db"),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
        )
    )
    try:
        described = pipeline.describe_frames(folder)
    finally:
        pipeline.close()
    said = "".join(capsys.readouterr())

    assert described == "", "a timeout must degrade to no frames, not raise"
    assert "ffmpeg" in said.lower(), f"the user has to be told frames were skipped: {said!r}"


def test_the_configured_limit_reaches_ffmpeg(tmp_path, monkeypatch):
    """The wiring, not the argument -- and a DISTINCTIVE value, not the default.

    Dropping `timeout_seconds=` from the pipeline's call left the suite green, because the
    parameter defaults to the same constant. Only a configured value that differs from the
    default can tell a wired argument from a coincidence.

    Third time this session: the rejudge budget and the fetch timeout had the same gap.
    """
    from winnow.pipeline import Pipeline

    seen = {}

    def record(command, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media.subprocess, "run", record)
    monkeypatch.setattr("winnow.pipeline.find_media_file", lambda target: tmp_path / "v.mp4")

    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text("a claim about throughput", encoding="utf-8")

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(tmp_path / "corpus.db"),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
            frame_timeout_seconds=97,
        )
    )
    try:
        pipeline.describe_frames(folder)
    finally:
        pipeline.close()

    assert seen["timeout"] == 97, (
        f"the configured limit never reached ffmpeg: {seen}"
    )


def test_frames_still_work_when_ffmpeg_answers(tmp_path, monkeypatch):
    """The guard: bounding it must not stop it doing the job."""

    def writes_frames(command, **kwargs):
        out = Path(command[-1]).parent
        out.mkdir(parents=True, exist_ok=True)
        for i in range(1, 4):
            (out / f"frame_{i:05d}.jpg").write_bytes(b"\xff\xd8\xff")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(media.subprocess, "run", writes_frames)

    frames = extract_frames(tmp_path / "video.mp4", tmp_path / "out", every_seconds=60)

    assert len(frames) == 3
    assert [f.seconds for f in frames] == [0, 60, 120]


def test_the_setting_is_documented():
    parameters = (
        Path(__file__).resolve().parent.parent / "docs" / "PARAMETERS.md"
    ).read_text(encoding="utf-8")

    assert "frame_timeout_seconds" in parameters
