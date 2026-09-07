"""Fetching material from a URL.

Winnow's pipeline works on a folder holding a transcript. Producing that folder from a
video URL is the step people actually have, so it lives here rather than in a documentation
page the user is expected to copy commands out of.

Three things this does NOT do, deliberately:

* It does not bundle or install yt-dlp. That stays a dependency you install, so the choice
  to run it is yours and the project distributes no downloader.
* It does not fetch silently. The exact command is printed before it runs, so what is about
  to happen to your machine and to someone's server is visible.
* It does not download video by default. Captions are a small text file; video is hundreds
  of megabytes and is only needed when a pack samples frames.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

# Captions only. Small, fast, and enough for everything except frame description.
CAPTION_ARGS = [
    "--skip-download",
    "--write-subs",
    "--write-auto-subs",
    "--sub-format", "vtt",
]

# Video capped at 720p: frames are downscaled to 640px before any model sees them, so a
# larger download buys nothing but time and disk.
VIDEO_ARGS = ["-f", "bv*[height<=720]+ba/b[height<=720]"]


class YtDlpMissing(RuntimeError):
    """yt-dlp is not installed. Deliberately not auto-installed on the user's behalf."""


class AcquisitionFailed(RuntimeError):
    """yt-dlp ran and did not produce a usable transcript."""


def looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def yt_dlp_command() -> list[str]:
    """How to invoke yt-dlp: the executable if present, else the module in this interpreter.

    Preferring the module means a `pip install yt-dlp` into the same environment works even
    when the console script is not on PATH, which is common on Windows.
    """
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    probe = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"], capture_output=True
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "yt_dlp"]
    raise YtDlpMissing(
        "yt-dlp is not installed, and Winnow does not install it for you.\n"
        "  Install it:  pip install -U yt-dlp\n"
        "  Then read docs/ACQUISITION.md -- downloading is your call to make, not the "
        "tool's, and the terms of the site you are fetching from are worth knowing."
    )


def fetch(
    url: str,
    dest: Path,
    *,
    languages: str = "en.*",
    with_video: bool = False,
    announce=print,
) -> Path:
    """Fetch captions (and optionally video) for `url` into `dest`. Returns the folder.

    This ALWAYS runs yt-dlp. Not re-fetching is the caller's decision, not this function's:
    `cli.cmd_ingest` keeps one folder per URL and skips calling here when the material it
    needs is already in it. The docstring used to promise "existing files are left alone",
    which described yt-dlp's own overwrite behaviour rather than anything this code does.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    command = [
        *yt_dlp_command(),
        *CAPTION_ARGS,
        "--sub-langs", languages,
        "-o", str(dest / "video.%(ext)s"),
    ]
    if with_video:
        command = [c for c in command if c != "--skip-download"] + VIDEO_ARGS
    command.append(url)

    announce("running: " + " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        raise AcquisitionFailed(
            f"yt-dlp exited {result.returncode} for {url}\n  "
            + "\n  ".join(tail)
            + "\n  A 403 or 429 is usually throttling -- wait and retry. "
            "'Unable to extract' usually means yt-dlp is out of date: pip install -U yt-dlp"
        )

    subtitles = sorted(dest.glob("*.vtt")) + sorted(dest.glob("*.srt"))
    if not subtitles:
        raise AcquisitionFailed(
            f"no captions available for {url}.\n"
            "  Winnow does not transcribe. To use this video, produce a transcript "
            "yourself and place it in a folder as transcript.txt -- "
            "docs/ACQUISITION.md shows how with faster-whisper."
        )

    announce(f"fetched {len(subtitles)} caption file(s) into {dest}")
    return dest


def cache_dir_for(url: str, root: Path) -> Path:
    """A stable per-URL folder, so the same link is not fetched twice.

    Named from the URL rather than a hash of it, so a person can look in the cache and see
    what is there.
    """
    import hashlib
    import re

    parsed = urlparse(url)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{parsed.netloc}{parsed.path}").strip("-")[:60]
    digest = hashlib.blake2b(url.encode("utf-8"), digest_size=4).hexdigest()
    return Path(root) / f"{slug}-{digest}"
