"""Local media handling. This module never touches the network.

Everything here works on what is already on disk: a transcript, a media file, or a folder
holding one. Fetching lives in `winnow.acquire`, which is the only module that reaches the
network and which shells out to yt-dlp (see docs/ACQUISITION.md).

Keeping that split means the whole pipeline is testable offline, and that Winnow works on
lecture recordings, podcasts, conference talks and internal archives exactly as well as on
anything fetched from a video site -- the fetch is a convenience at the front, not a
requirement.
"""

from __future__ import annotations

import base64
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_FRAME_TIMEOUT

# Extensions treated as media. Subtitles are explicitly NOT media -- see find_media_file.
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4a", ".mp3", ".wav", ".flac"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa", ".sub"}
# yt-dlp names YouTube's ORIGINAL caption track `<name>.<lang>-orig.<ext>` and its machine
# translation `<name>.<lang>.<ext>`. Both can end up in one folder, and the original is the
# one that says what was actually spoken.
ORIGINAL_TRACK_SUFFIX = "-orig"
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".mdx"}


class FFmpegMissing(RuntimeError):
    pass


class FramesTimedOut(RuntimeError):
    """ffmpeg did not finish within `frame_timeout_seconds`.

    Its own class rather than a bare `subprocess.TimeoutExpired`, because the caller has to
    catch it BY NAME: `Pipeline.describe_frames` degrades to no frames for any reason frames
    are unavailable, and a timeout belongs in that set -- but only if it can be told apart
    from a genuine bug escaping the same call.
    """


def find_media_file(folder: Path) -> Path | None:
    """The media file in a folder, ignoring subtitles that sit beside it.

    A naive glob such as `video.*` also matches `video.en.vtt`. When it does, the caller
    concludes the media is already present, skips acquiring it, and then extracts frames
    from a subtitle file -- producing an empty result with no error anywhere. Subtitle
    extensions are therefore excluded explicitly rather than relying on sort order.
    """
    if not folder.is_dir():
        return None
    candidates = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
    ]
    return candidates[0] if candidates else None


def find_subtitle_file(folder: Path) -> Path | None:
    """The best subtitle file in a folder: an original track before a translation.

    This used to return whichever sorted first. `video.en-orig.vtt` beat `video.en.vtt` only
    because `-` sorts before `.` in ASCII -- the right answer by accident, and one that stops
    being right as soon as a file is named anything else. `en` is YouTube's machine
    translation INTO English; `en-orig` is what was said.
    """
    if not folder.is_dir():
        return None
    subtitles = [
        p
        for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in SUBTITLE_EXTENSIONS
    ]
    if not subtitles:
        return None
    # The language tag is the last dot-separated part of the stem, so a file called
    # `my-original-talk.vtt` is not mistaken for an original track.
    originals = [
        p
        for p in subtitles
        if p.stem.rsplit(".", 1)[-1].lower().endswith(ORIGINAL_TRACK_SUFFIX)
    ]
    return (originals or subtitles)[0]


# -- transcripts ---------------------------------------------------------------

_TIMESTAMP = re.compile(r"^\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}\s*-->")
_TAG = re.compile(r"<[^>]+>")


def parse_subtitles(text: str) -> str:
    """Flatten a WebVTT or SRT file into plain prose.

    Consecutive duplicate lines are collapsed: rolling captions repeat each line as they
    scroll, which would otherwise triple the transcript and skew everything downstream.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if _TIMESTAMP.search(line) or "-->" in line:
            continue
        if line.isdigit():
            continue
        line = _TAG.sub("", line).strip()
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return " ".join(lines)


def load_transcript(path: Path) -> str:
    """Read a transcript from a subtitle file or a plain text file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in SUBTITLE_EXTENSIONS:
        return parse_subtitles(text)
    return text.strip()


def transcript_source(target: Path) -> Path | None:
    """Which file a transcript would be read from, or None.

    Separate from reading it so that the caller can SAY which file it used. Choosing
    silently between two files in a folder is the fault underneath everything below.

    In a folder, a hand-placed transcript beats fetched captions. That order used to be the
    other way round, which made the documented remedy for bad captions do nothing: `winnow
    ingest <url>` tells you to "produce a transcript yourself and place it in a folder as
    transcript.txt", and in a folder that already held a `.vtt` the file you just wrote was
    ignored without a word.

    The deciding argument is which mistake the user can undo. A `transcript.txt` that should
    not have won is a file they made and can rename. A `.vtt` that should not have won sits
    in a cache folder named by a hash of the URL, which nothing tells them to look in. Only
    one of those is recoverable with what they already know -- and a hand-placed file is the
    only one whose presence is a decision rather than a by-product of fetching.
    """
    if target.is_file():
        if target.suffix.lower() in SUBTITLE_EXTENSIONS | TEXT_EXTENSIONS:
            return target
        return None
    for name in ("transcript.txt", "transcript.md"):
        candidate = target / name
        if candidate.is_file():
            return candidate
    return find_subtitle_file(target)


def transcript_for(target: Path) -> str | None:
    """Best available transcript for a file or a folder, without transcribing audio."""
    chosen = transcript_source(target)
    return load_transcript(chosen) if chosen else None


# -- frames --------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    index: int
    seconds: float
    path: Path

    def to_base64(self) -> str:
        return base64.b64encode(self.path.read_bytes()).decode("ascii")


def ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, check=True, timeout=20
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def extract_frames(
    media: Path,
    out_dir: Path,
    every_seconds: int = 30,
    limit: int = 40,
    timeout_seconds: int = DEFAULT_FRAME_TIMEOUT,
) -> list[Frame]:
    """Sample frames with ffmpeg. Returns [] for audio-only input rather than raising.

    BOUNDED. `ffmpeg_available` above has always passed a timeout to its version probe; this
    call, the one that actually decodes a video, had none. A truncated download, a malformed
    container or a stream ffmpeg cannot make sense of leaves it spinning, and Winnow waits
    with no output and no end -- the same defect as the unbounded yt-dlp call in
    `winnow.acquire`, in the module next door, which was fixed without this one travelling.

    A timeout is `FramesTimedOut`, not a bare `subprocess.TimeoutExpired`, so that
    `Pipeline.describe_frames` can catch it by name: frames are the optional half of an
    ingest and losing them must not lose the transcript, but a genuine bug escaping the same
    call must not be swallowed with them.
    """
    if not ffmpeg_available():
        raise FFmpegMissing(
            "ffmpeg not found on PATH. On Windows, after installing it you must open a new "
            "shell before it is visible -- see docs/ACQUISITION.md."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%05d.jpg")
    try:
        subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-i", str(media),
                "-vf", f"fps=1/{every_seconds},scale=640:-1",
                "-frames:v", str(limit), pattern,
            ],
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise FramesTimedOut(
            f"ffmpeg did not finish sampling {media.name} within {timeout_seconds} "
            "seconds.\n"
            "  Sampling decodes through the file, so a long recording is genuinely slow -- "
            "raise `frame_timeout_seconds` in winnow.json if that is what this is. A file "
            "that never finishes is usually truncated or in a container ffmpeg cannot read."
        ) from exc
    frames = []
    for i, p in enumerate(sorted(out_dir.glob("frame_*.jpg"))):
        frames.append(Frame(index=i, seconds=i * every_seconds, path=p))
    return frames
