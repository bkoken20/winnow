"""Fetching from a URL.

The pipeline works on a folder containing a transcript. Producing that folder from a link is
the step people actually have, so it belongs in the tool rather than in a documentation page
users are expected to copy commands out of.

Network is never touched here: yt-dlp is stubbed. What is tested is that the right command
is built, that the result is used, that failures are legible, and that nothing is fetched
silently.
"""

import subprocess
from pathlib import Path

import pytest

from winnow import acquire
from winnow.acquire import (
    AcquisitionFailed,
    YtDlpMissing,
    cache_dir_for,
    fetch,
    looks_like_url,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://youtu.be/abc123", True),
        ("http://example.com/talk", True),
        # Relative rather than absolute: the repo forbids machine paths in tracked files,
        # and these only need to be non-URLs.
        ("./talk", False),
        ("../archive/talk", False),
        ("talk.vtt", False),
        ("", False),
        ("ftp://example.com/x", False),
    ],
)
def test_url_detection(value, expected):
    assert looks_like_url(value) is expected


def test_the_same_url_always_maps_to_the_same_folder(tmp_path):
    """Caching only works if a link resolves to one place."""
    a = cache_dir_for("https://youtu.be/abc123", tmp_path)
    b = cache_dir_for("https://youtu.be/abc123", tmp_path)
    assert a == b


def test_different_urls_do_not_collide(tmp_path):
    a = cache_dir_for("https://youtu.be/abc123", tmp_path)
    b = cache_dir_for("https://youtu.be/xyz789", tmp_path)
    assert a != b


def test_the_cache_folder_is_readable_by_a_person(tmp_path):
    """A cache you cannot inspect is a cache you cannot trust."""
    folder = cache_dir_for("https://youtu.be/abc123", tmp_path)
    assert "youtu-be" in folder.name and "abc123" in folder.name


class FakeYtDlp:
    """Stands in for the real thing: records the command, writes a caption file."""

    def __init__(self, returncode=0, write_captions=True, stderr=""):
        self.returncode = returncode
        self.write_captions = write_captions
        self.stderr = stderr
        self.command = None

    def __call__(self, command, **kwargs):
        self.command = command
        if self.write_captions:
            out = Path(command[command.index("-o") + 1]).parent
            out.mkdir(parents=True, exist_ok=True)
            (out / "video.en.vtt").write_text("WEBVTT\n\nhello\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    fake = FakeYtDlp()
    monkeypatch.setattr(acquire.subprocess, "run", fake)
    return fake


def test_captions_only_by_default(tmp_path, stub):
    """Video is hundreds of megabytes; captions are a text file."""
    fetch("https://youtu.be/abc", tmp_path / "out", announce=lambda *_: None)
    assert "--skip-download" in stub.command
    assert "-f" not in stub.command


def test_with_video_downloads_the_video_capped_at_720p(tmp_path, stub):
    """Frames are downscaled to 640px, so a larger download buys nothing."""
    fetch("https://youtu.be/abc", tmp_path / "out", with_video=True, announce=lambda *_: None)
    assert "--skip-download" not in stub.command
    assert any("height<=720" in part for part in stub.command)


def test_the_command_is_announced_before_it_runs(tmp_path, stub):
    """Nothing is fetched silently: what hits the network must be visible first."""
    said = []
    fetch("https://youtu.be/abc", tmp_path / "out", announce=said.append)
    assert any("running:" in line and "yt-dlp" in line for line in said)


def test_the_requested_language_is_passed_through(tmp_path, stub):
    fetch("https://youtu.be/abc", tmp_path / "out", languages="de.*", announce=lambda *_: None)
    assert "de.*" in stub.command


def test_a_failing_yt_dlp_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(
        acquire.subprocess, "run", FakeYtDlp(returncode=1, stderr="ERROR: Unable to extract")
    )
    with pytest.raises(AcquisitionFailed) as exc:
        fetch("https://youtu.be/abc", tmp_path / "out", announce=lambda *_: None)
    assert "pip install -U yt-dlp" in str(exc.value)


def test_a_video_with_no_captions_says_winnow_will_not_transcribe(tmp_path, monkeypatch):
    """The honest boundary: no captions is a stop, not a silent empty result."""
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(acquire.subprocess, "run", FakeYtDlp(write_captions=False))
    with pytest.raises(AcquisitionFailed) as exc:
        fetch("https://youtu.be/abc", tmp_path / "out", announce=lambda *_: None)
    message = str(exc.value)
    assert "does not transcribe" in message
    assert "faster-whisper" in message


def test_a_missing_yt_dlp_does_not_try_to_install_it(tmp_path, monkeypatch):
    """Installing a downloader on someone's behalf is not the tool's decision to make.

    The message alone is not enough to assert this: an earlier version of this test passed
    while a `pip install` was running underneath it. Every subprocess call is recorded and
    checked.
    """
    calls = []

    def record(command, *args, **kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(acquire.shutil, "which", lambda _: None)
    monkeypatch.setattr(acquire.subprocess, "run", record)

    with pytest.raises(YtDlpMissing) as exc:
        acquire.yt_dlp_command()

    assert "does not install it for you" in str(exc.value)
    assert "pip install -U yt-dlp" in str(exc.value)

    flat = " ".join(" ".join(c) for c in calls)
    assert "pip" not in flat, f"the tool tried to install something: {calls}"
    assert "install" not in flat, f"the tool tried to install something: {calls}"


def test_the_fetched_folder_is_what_the_pipeline_already_understands(tmp_path, stub):
    """Acquisition ends where the existing pipeline begins -- no second code path."""
    from winnow.media import transcript_for

    folder = fetch("https://youtu.be/abc", tmp_path / "out", announce=lambda *_: None)
    assert transcript_for(folder) == "hello"
