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

import re
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


# A host-ish token followed by a path: "youtu.be/x", "www.youtube.com/watch?v=x". Deliberately
# narrow -- it must not fire on an ordinary relative path like "notes/talk.txt", so a dot in
# the first segment is required and the part after it has to look like a TLD.
_HOSTLIKE = re.compile(r"^(?:www\.)?[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?:[/?].*)?$")


def why_not_a_url(value: str) -> str | None:
    """Why this string ALMOST looks like a link, or None if it does not look like one.

    Anything that is not a usable URL falls through to the path branch, where a pasted link
    was reported as "no such file or folder" -- with the separators flipped by `Path()`, so
    the string quoted back was not even the one the user typed. YouTube displays links
    without their scheme, which makes dropping it the default mistake rather than an exotic
    one.
    """
    if looks_like_url(value):
        return None

    scheme, _, rest = value.partition("://")
    if rest or value.endswith("://"):
        if scheme in ("http", "https"):
            return (
                f"{value!r} has a scheme but no address after it. A full link looks like "
                "https://youtu.be/VIDEO_ID"
            )
        return (
            f"{value!r} starts with {scheme + '://'!r}, which is not a scheme Winnow can "
            "fetch. Use http:// or https:// -- most likely https://"
        )

    if _HOSTLIKE.match(value):
        return (
            f"{value!r} looks like a link with no scheme. Try https://{value}\n"
            "  (YouTube shows links without the https:// part; Winnow needs it.)"
        )
    return None


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


def announce_flushed(message: str) -> None:
    """Print and FLUSH. The default for `fetch`, and the flushing is the point.

    "The exact command is printed before it runs" is a privacy guarantee, not a progress
    message -- nothing should reach the network without appearing on screen first. A bare
    `print` is block-buffered when stdout is a pipe, so piped into a log, `| tee` or CI the
    announcement sat in the buffer while yt-dlp ran and failed, and the user read the error
    ABOVE the command that caused it. Observed against a real 429 from YouTube.
    """
    print(message, flush=True)


def fetch(
    url: str,
    dest: Path,
    *,
    languages: str = "en.*",
    with_video: bool = False,
    announce=announce_flushed,
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
            + "\n  yt-dlp's own message is above and is the thing to read. Common causes:\n"
            "    - the video is unavailable, private, deleted or region-locked\n"
            "    - 403 or 429: throttling. Wait and retry; Winnow does not retry for you\n"
            "    - 'Unable to extract': yt-dlp is out of date. pip install -U yt-dlp\n"
            "    - 'Sign in to confirm': the site is gating it; see docs/ACQUISITION.md"
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
