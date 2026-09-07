"""`--with-video` must not be silently ignored because captions are already cached.

`winnow ingest <url>` caches per URL, which is right: re-running a link should not
re-download it. But the cache hit is decided on "is the folder non-empty", and a folder
holding only captions is non-empty. So:

    winnow ingest https://...                 # captions cached
    winnow ingest https://... --with-video    # "using cached material", no video fetched

The second command asks for the video explicitly, is told nothing, downloads nothing, and
then describes no frames -- because `describe_frames` finds no media file and returns "" by
design, since a missing optional half must not fail an ingest. Every layer behaves
correctly and the user's explicit request disappears between them.
"""
from __future__ import annotations

import json

import pytest

from winnow import cli


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps(
            {
                "corpus_path": str(tmp_path / "corpus.db"),
                "cache_path": str(tmp_path / "cache"),
                "embed_backend": "hashing",
            }
        ),
        encoding="utf-8",
    )
    return config


def _fetch_calls(monkeypatch):
    """Record fetch() calls and lay down captions, as a real fetch would."""
    calls = []

    def fake_fetch(url, dest, *, languages="en.*", with_video=False, announce=print):
        calls.append({"url": url, "dest": dest, "with_video": with_video})
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "video.en.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello there\n", encoding="utf-8"
        )
        if with_video:
            (dest / "video.mp4").write_bytes(b"\x00")
        return dest

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    return calls


def test_a_second_run_reuses_the_cache(configured, monkeypatch, capsys):
    """The behaviour worth keeping: the same link is not fetched twice."""
    calls = _fetch_calls(monkeypatch)
    url = "https://youtu.be/abc123"

    cli.main(["--config", str(configured), "ingest", url])
    cli.main(["--config", str(configured), "ingest", url])

    assert len(calls) == 1, "the same URL should not be fetched twice"
    assert "cached" in capsys.readouterr().out


def test_asking_for_video_after_a_captions_only_fetch_actually_fetches_it(
    configured, monkeypatch, capsys
):
    calls = _fetch_calls(monkeypatch)
    url = "https://youtu.be/abc123"

    cli.main(["--config", str(configured), "ingest", url])
    cli.main(["--config", str(configured), "ingest", url, "--with-video"])
    capsys.readouterr()

    assert len(calls) == 2, (
        "--with-video was ignored because captions were already cached; the user asked "
        "for the video explicitly and nothing was downloaded or said"
    )
    assert calls[1]["with_video"] is True


def test_video_already_cached_is_not_fetched_again(configured, monkeypatch, capsys):
    """The fix must not turn --with-video into an unconditional re-download."""
    calls = _fetch_calls(monkeypatch)
    url = "https://youtu.be/abc123"

    cli.main(["--config", str(configured), "ingest", url, "--with-video"])
    cli.main(["--config", str(configured), "ingest", url, "--with-video"])
    capsys.readouterr()

    assert len(calls) == 1, "the video is already there; do not fetch it twice"


def test_refetch_still_overrides_everything(configured, monkeypatch, capsys):
    calls = _fetch_calls(monkeypatch)
    url = "https://youtu.be/abc123"

    cli.main(["--config", str(configured), "ingest", url])
    cli.main(["--config", str(configured), "ingest", url, "--refetch"])
    capsys.readouterr()

    assert len(calls) == 2
