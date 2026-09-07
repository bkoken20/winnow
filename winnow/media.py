"""Local media handling. This module never touches the network.

Acquisition is the user's job (see docs/ACQUISITION.md). Winnow accepts a transcript, a
media file, or a folder that already exists on disk. That boundary is deliberate: it keeps
the project clear of distributing a downloader, makes the whole pipeline testable offline,
and means Winnow works on lecture recordings, podcasts, conference talks and internal
archives just as well as on anything downloaded from a video site.
"""

from __future__ import annotations

import base64
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Extensions treated as media. Subtitles are explicitly NOT media -- see find_media_file.
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4a", ".mp3", ".wav", ".flac"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa", ".sub"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".mdx"}


class FFmpegMissing(RuntimeError):
    pass


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
    if not folder.is_dir():
        return None
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in SUBTITLE_EXTENSIONS:
            return p
    return None


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


def transcript_for(target: Path) -> str | None:
    """Best available transcript for a file or a folder, without transcribing audio."""
    if target.is_file():
        if target.suffix.lower() in SUBTITLE_EXTENSIONS | TEXT_EXTENSIONS:
            return load_transcript(target)
        return None
    subtitle = find_subtitle_file(target)
    if subtitle:
        return load_transcript(subtitle)
    for name in ("transcript.txt", "transcript.md"):
        candidate = target / name
        if candidate.exists():
            return load_transcript(candidate)
    return None


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
    media: Path, out_dir: Path, every_seconds: int = 30, limit: int = 40
) -> list[Frame]:
    """Sample frames with ffmpeg. Returns [] for audio-only input rather than raising."""
    if not ffmpeg_available():
        raise FFmpegMissing(
            "ffmpeg not found on PATH. On Windows, after installing it you must open a new "
            "shell before it is visible -- see docs/ACQUISITION.md."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%05d.jpg")
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y", "-i", str(media),
            "-vf", f"fps=1/{every_seconds},scale=640:-1",
            "-frames:v", str(limit), pattern,
        ],
        capture_output=True,
        check=False,
    )
    frames = []
    for i, p in enumerate(sorted(out_dir.glob("frame_*.jpg"))):
        frames.append(Frame(index=i, seconds=i * every_seconds, path=p))
    return frames
