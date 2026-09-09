"""A fetch could hang forever, silently, and a video download showed nothing while it ran.

`_run_yt_dlp` called `subprocess.run(command, capture_output=True, text=True)`. No timeout,
so a stalled connection or a site that accepts and never answers leaves Winnow waiting with
no output and no way to know whether anything is happening — the "running: yt-dlp ..." line
is on screen and then nothing, indefinitely. Ctrl-C is the only exit, and it kills the run
rather than the fetch.

`capture_output=True` is the second half. For captions that is right: a couple of seconds,
and the text is wanted for the error message. For `--with-video` it is not — that is
hundreds of megabytes with yt-dlp's own progress display swallowed, so a download that is
working looks exactly like one that has hung.

So: bounded always, and visible when there is something worth watching.

Reported by an external review.
"""
from __future__ import annotations

import pathlib
import subprocess

import pytest

from winnow import acquire
from winnow.acquire import AcquisitionFailed, fetch
from winnow.config import Config

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
PACKS_ROOT = ROOT_DIR / "packs"


def test_a_hung_fetch_is_stopped_rather_than_waited_on(tmp_path, monkeypatch):
    """The failure this prevents has no other end: no output, no progress, no limit."""

    def hangs(command, **kwargs):
        assert "timeout" in kwargs, "subprocess.run was called with no timeout at all"
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(acquire.subprocess, "run", hangs)
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])

    with pytest.raises(AcquisitionFailed) as raised:
        fetch("https://example.com/watch?v=x", tmp_path, announce=lambda m: None)

    said = str(raised.value)
    assert "timed out" in said.lower() or "timeout" in said.lower(), said
    assert "fetch_timeout_seconds" in said, (
        f"name the setting that changes it, or the message is a dead end: {said!r}"
    )


def test_the_timeout_is_configurable(tmp_path, monkeypatch):
    seen = {}

    def record(command, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(acquire.subprocess, "run", record)
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])

    with pytest.raises(AcquisitionFailed):
        fetch(
            "https://example.com/watch?v=x",
            tmp_path,
            announce=lambda m: None,
            timeout_seconds=17,
        )

    assert seen["timeout"] == 17


def test_the_default_comes_from_the_configuration():
    assert Config().fetch_timeout_seconds > 0
    assert Config(fetch_timeout_seconds=42).fetch_timeout_seconds == 42


def test_there_is_only_one_default_timeout():
    """Found by walking the fix: two constants held 600 and nothing held them together.

    The same shape as `status` and the pipeline comparing different model names -- two
    values that agree until one of them is edited. `acquire` imports the constant rather
    than declaring its own, so this asserts identity, not equality.
    """
    from winnow.config import DEFAULT_FETCH_TIMEOUT

    assert acquire.DEFAULT_FETCH_TIMEOUT is DEFAULT_FETCH_TIMEOUT
    assert Config().fetch_timeout_seconds == DEFAULT_FETCH_TIMEOUT


def test_a_caption_fetch_still_captures_its_output(tmp_path, monkeypatch):
    """The text is what the failure message quotes, so captions must keep capturing it."""
    seen = {}

    def record(command, **kwargs):
        seen["capture"] = kwargs.get("capture_output")
        return subprocess.CompletedProcess(command, 1, "", "ERROR: no such video")

    monkeypatch.setattr(acquire.subprocess, "run", record)
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])

    with pytest.raises(AcquisitionFailed) as raised:
        fetch("https://example.com/watch?v=x", tmp_path, announce=lambda m: None)

    assert seen["capture"] is True
    assert "no such video" in str(raised.value), "the captured message must reach the user"


def test_a_video_download_is_watched_rather_than_captured(tmp_path, monkeypatch):
    """Hundreds of megabytes with the progress display swallowed looks like a hang."""
    seen = {}

    def record(command, **kwargs):
        seen["capture"] = kwargs.get("capture_output")
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, None, None)

    monkeypatch.setattr(acquire.subprocess, "run", record)
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])
    (tmp_path / "video.en-orig.vtt").write_text("WEBVTT\n\nhello\n", encoding="utf-8")

    fetch(
        "https://example.com/watch?v=x",
        tmp_path,
        with_video=True,
        announce=lambda m: None,
    )

    assert seen["capture"] is not True, (
        "yt-dlp's progress was captured, so a working download shows nothing"
    )


def test_a_failed_video_download_still_says_where_to_look(tmp_path, monkeypatch):
    """Nothing was captured, so the message cannot quote it -- and must say so."""

    def fails(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, None, None)

    monkeypatch.setattr(acquire.subprocess, "run", fails)
    monkeypatch.setattr(acquire, "yt_dlp_command", lambda: ["yt-dlp"])

    with pytest.raises(AcquisitionFailed) as raised:
        fetch(
            "https://example.com/watch?v=x",
            tmp_path,
            with_video=True,
            announce=lambda m: None,
        )

    said = str(raised.value)
    assert "None" not in said, f"a captured-nothing placeholder leaked into the message: {said!r}"

    # The SHAPE, not a word. `"above" in said` passed even with the fallback deleted,
    # because the standing advice block below already says "yt-dlp's own message is above".
    # What must not happen is an empty quotation where the captured text would have gone.
    lines = said.splitlines()
    assert lines[0].startswith("yt-dlp exited")
    assert lines[1].strip(), f"the quoted output is blank: {said!r}"
    assert "output is above" in lines[1], (
        f"with nothing captured, the second line must point at the terminal: {said!r}"
    )


def test_the_command_line_passes_the_configured_timeout(tmp_path, monkeypatch):
    """The wiring, not the argument. Dropping it in `cmd_ingest` left the suite green."""
    import json

    from winnow import cli

    seen = {}

    def record(url, dest, **kwargs):
        seen.update(kwargs)
        dest = __import__("pathlib").Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "video.en-orig.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n", encoding="utf-8"
        )
        return dest

    monkeypatch.setattr(cli, "fetch", record)

    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
                "cache_path": str(tmp_path / "cache"),
                "fetch_timeout_seconds": 123,
            }
        ),
        encoding="utf-8",
    )

    cli.main(["ingest", "https://youtu.be/abc", "--config", str(config)])

    assert seen.get("timeout_seconds") == 123, (
        f"the configured timeout never reached the fetch: {seen}"
    )


def test_the_field_default_is_the_constant_not_a_copy_of_it():
    """The MECHANISM, which no value comparison can check.

    Replacing `DEFAULT_FETCH_TIMEOUT` with a literal `600` leaves every value equal, so a
    test of the values passes. What it removes is the thing that keeps them equal after
    someone edits one of them.
    """
    source = (ROOT_DIR / "winnow" / "config.py").read_text(encoding="utf-8")

    assert "fetch_timeout_seconds: int = DEFAULT_FETCH_TIMEOUT" in source, (
        "the dataclass default must BE the constant, not a second copy of its value"
    )
    assert "from .config import DEFAULT_FETCH_TIMEOUT" in (
        ROOT_DIR / "winnow" / "acquire.py"
    ).read_text(encoding="utf-8"), "acquire must import the constant, not declare one"
