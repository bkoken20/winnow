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

from .config import DEFAULT_FETCH_TIMEOUT

# Captions only. Small, fast, and enough for everything except frame description.
#
# --sleep-requests paces the metadata calls. yt-dlp names it as the flag that addresses the
# cause of a YouTube 429, and docs/ACQUISITION.md has recommended it to users since before
# this command used it. The trade is two seconds against a block that lasts minutes at best
# and several hours at worst, with no way to query the remaining time and no appeal.
CAPTION_ARGS = [
    "--skip-download",
    "--write-subs",
    "--write-auto-subs",
    "--sub-format", "vtt",
    "--sleep-requests", "2",
]

# The ORIGINAL caption track, not a translation of it.
#
# `--sub-langs` is a regex. The previous default, "en.*", matched BOTH tracks YouTube offers
# for an English video:
#
#     en-orig   English (Original)   <- the ASR track
#     en        English              <- YouTube's machine translation, into English
#
# So every fetch downloaded the original and a translation of it -- measured byte-identical,
# 206,817 bytes, same SHA -- and yt-dlp's maintainers name auto-translated captions as the
# specific cause of the subtitle HTTP 429. That block cost this project most of a day.
#
# The same video offers 157 automatic caption languages; all but the original are machine
# translations, so the wildcard was reaching into exactly the wrong pool.
DEFAULT_CAPTION_LANGS = "en-orig"

# Used only when the original track does not exist: a video in another language, or one whose
# English captions are manual rather than automatic. Then the translation IS what is wanted.
CAPTION_TRANSLATION_FALLBACK = "en"

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


# Extensions Winnow can actually read. A value ending in one of these is a filename even
# when it also looks like a host, which "README.md" and "talk.txt" both do.
_READABLE_SUFFIXES = frozenset(
    {".txt", ".md", ".markdown", ".mdx", ".vtt", ".srt", ".ass", ".ssa", ".sub",
     ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4a", ".mp3", ".wav", ".flac", ".json"}
)

# A host-ish token followed by A PATH: "youtu.be/x", "www.youtube.com/watch?v=x". The
# trailing `[/?]` is now REQUIRED, and that is the whole substance of this pattern.
#
# It was optional, so a bare dotted name matched and any filename Winnow does not read was
# answered with link advice: `data.backup`, `report.docx`, `archive.zip`, `notes.tar.gz`.
# That was patched once by excluding the extensions Winnow READS, which is a list of
# instances -- the class is "a filename", and no extension list describes it. `.zip` is a
# real top-level domain, so no rule can separate `archive.zip` the file from `archive.zip`
# the host.
#
# It is genuinely ambiguous, so the answer is too: a bare dotted name falls through to the
# path branch, which reports it as missing AND offers the link reading. What is not
# ambiguous is a host with a path after it -- which is exactly what a link pasted without
# its scheme looks like, because YouTube always shows one.
_HOSTLIKE = re.compile(r"^(?:www\.)?[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}[/?].*$")


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


def is_obviously_a_filename(value: str) -> bool:
    """Does this name end in something Winnow reads?

    Used to decide whether the LINK reading is worth mentioning at all, not whether the
    string is a host -- the host pattern settles that by requiring a path. `talk.txt` and
    `video.mp4` are files whatever they resemble, and an earlier round decided exactly that;
    offering "if you meant a link" for them is noise that contradicts a settled answer.

    `data.backup` and `archive.zip` are not on the list and never will be, because the list
    is of things Winnow READS. Those stay ambiguous, and get both readings.
    """
    return Path(value).suffix.lower() in _READABLE_SUFFIXES


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


def _run_yt_dlp(
    url: str,
    dest: Path,
    languages: str,
    with_video: bool,
    announce,
    timeout_seconds: int = DEFAULT_FETCH_TIMEOUT,
):
    """Run yt-dlp once: bounded always, and watched when there is something to watch.

    CAPTURED for captions. That is seconds of work, and the text is what the failure
    message quotes -- yt-dlp explains itself far better than an exit code does.

    NOT captured for `--with-video`. That is hundreds of megabytes, and capturing swallows
    yt-dlp's own progress display until the process ends, so a download that is working
    looks exactly like one that has hung. Letting it write straight to the terminal is the
    progress report; the failure message then points at it rather than quoting nothing.

    TIMED either way. `subprocess.run` without a timeout waits forever, so a stalled
    connection or a site that accepts and never answers left Winnow with the "running:"
    line on screen and no end -- and Ctrl-C killed the whole run rather than the fetch.
    """
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
    try:
        if with_video:
            return subprocess.run(command, timeout=timeout_seconds)
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        raise AcquisitionFailed(
            f"yt-dlp timed out after {timeout_seconds} seconds for {url}.\n"
            "  Nothing was reported for that whole time, which usually means the "
            "connection stalled rather than that the work is large.\n"
            "  Raise `fetch_timeout_seconds` in winnow.json if the download is genuinely "
            "that long, or retry -- Winnow does not retry for you."
        ) from exc


def _captions_in(dest: Path) -> list[Path]:
    return sorted(dest.glob("*.vtt")) + sorted(dest.glob("*.srt"))


def fetch(
    url: str,
    dest: Path,
    *,
    languages: str = DEFAULT_CAPTION_LANGS,
    with_video: bool = False,
    announce=announce_flushed,
    timeout_seconds: int = DEFAULT_FETCH_TIMEOUT,
) -> Path:
    """Fetch captions (and optionally video) for `url` into `dest`. Returns the folder.

    This ALWAYS runs yt-dlp. Not re-fetching is the caller's decision, not this function's:
    `cli.cmd_ingest` keeps one folder per URL and skips calling here when the material it
    needs is already in it.

    Asks for the ORIGINAL track and falls back to a translation only when there is none --
    see DEFAULT_CAPTION_LANGS. The fallback costs one extra request and happens only for
    material whose original language is not English.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    result = _run_yt_dlp(url, dest, languages, with_video, announce, timeout_seconds)

    if result.returncode == 0 and not _captions_in(dest) and languages == DEFAULT_CAPTION_LANGS:
        # No original English track: the video is in another language, so the machine
        # translation is the only English there is -- and now it is what the reader wants,
        # rather than a duplicate of something already fetched.
        announce(
            f"no {DEFAULT_CAPTION_LANGS!r} track; trying {CAPTION_TRANSLATION_FALLBACK!r} "
            "(YouTube's machine translation)"
        )
        # Captions only, whatever the first call was asked for. The fallback is reached
        # only when that call SUCCEEDED and simply wrote no subtitles, so the media -- if it
        # was wanted -- is already on disk. Passing with_video through re-requested hundreds
        # of megabytes that had just been fetched.
        result = _run_yt_dlp(
            url, dest, CAPTION_TRANSLATION_FALLBACK, False, announce, timeout_seconds
        )

    if result.returncode != 0:
        # Nothing is captured for a video download -- it went to the terminal, where the
        # user has already read it. Quoting the empty capture would print "None".
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        quoted = "\n  ".join(tail) if tail else "(yt-dlp's output is above)"
        raise AcquisitionFailed(
            f"yt-dlp exited {result.returncode} for {url}\n  "
            + quoted
            + "\n  yt-dlp's own message is above and is the thing to read. Common causes:\n"
            "    - the video is unavailable, private, deleted or region-locked\n"
            "    - members-only or otherwise gated: you need access to it, which is\n"
            "      between you and the site. Winnow will not authenticate for you\n"
            "    - 403 or 429: throttling. Wait and retry; Winnow does not retry for you\n"
            "    - 'Unable to extract': yt-dlp is out of date. pip install -U yt-dlp\n"
            "    - 'Sign in to confirm you're not a bot': YouTube's bot check, not a\n"
            "      gate on the content. See docs/ACQUISITION.md"
        )

    subtitles = _captions_in(dest)
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
