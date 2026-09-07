"""Media discovery and transcript parsing.

The first test here guards a real defect: a `video.*` glob also matches `video.en.vtt`, and when it does the pipeline believes the media is present, skips
acquiring it, and extracts frames from a subtitle file -- producing an empty result with no
error anywhere.
"""

from pathlib import Path

from winnow.media import (
    find_media_file,
    find_subtitle_file,
    parse_subtitles,
    transcript_for,
)


def test_subtitle_alone_is_not_treated_as_media(tmp_path: Path):
    """A folder holding only captions has no media file. This is the whole bug."""
    (tmp_path / "video.en.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n")
    assert find_media_file(tmp_path) is None


def test_media_found_alongside_subtitles(tmp_path: Path):
    (tmp_path / "video.en.vtt").write_text("WEBVTT\n")
    (tmp_path / "video.mp4").write_bytes(b"\x00\x00")
    found = find_media_file(tmp_path)
    assert found is not None and found.suffix == ".mp4"


def test_subtitle_is_still_discoverable(tmp_path: Path):
    (tmp_path / "video.en.vtt").write_text("WEBVTT\n")
    assert find_subtitle_file(tmp_path).suffix == ".vtt"


def test_srt_is_not_media_either(tmp_path: Path):
    (tmp_path / "talk.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    assert find_media_file(tmp_path) is None


# -- transcript parsing --------------------------------------------------------

VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
setting the context window

00:00:03.000 --> 00:00:05.000
setting the context window
matters more than you think

00:00:05.000 --> 00:00:07.000
<c.colorE5E5E5>matters more than you think</c>
"""


def test_vtt_parsing_strips_timestamps_headers_and_tags():
    text = parse_subtitles(VTT)
    assert "-->" not in text
    assert "WEBVTT" not in text
    assert "Kind:" not in text
    assert "<c." not in text
    assert "setting the context window" in text


def test_rolling_captions_are_deduplicated():
    """Scrolling captions repeat each line; left in, they triple the transcript."""
    text = parse_subtitles(VTT)
    assert text.count("matters more than you think") == 1
    assert text.count("setting the context window") == 1


def test_transcript_for_prefers_a_real_transcript_file(tmp_path: Path):
    (tmp_path / "transcript.txt").write_text("plain text transcript")
    assert transcript_for(tmp_path) == "plain text transcript"


def test_transcript_for_returns_none_when_only_media_present(tmp_path: Path):
    """No transcription happens here, so media alone is not enough."""
    (tmp_path / "video.mp4").write_bytes(b"\x00")
    assert transcript_for(tmp_path) is None
