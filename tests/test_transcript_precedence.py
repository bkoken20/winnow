"""When a folder offers more than one transcript, which one wins -- and say so.

`transcript_for` prefers a subtitle file over `transcript.txt`, and nothing says so. That
matters because the *documented* way to handle bad captions is to write a transcript
yourself: `winnow ingest <url>` says "produce a transcript yourself and place it in a folder
as transcript.txt", and docs/ACQUISITION.md shows how with faster-whisper. Follow that advice
in a folder that already holds captions and Winnow silently ignores the file you just made.

Which mistake can the user undo? A `transcript.txt` that should not have won is one they
created and can rename. A `.vtt` that should not have won sits inside a cache folder named by
a hash of the URL, which nothing in the documentation tells them to look in. So the
hand-placed file wins: it is the only one whose presence is a decision.

Among subtitles, the choice was `sorted()` -- and `video.en-orig.vtt` beats `video.en.vtt`
only because `-` sorts before `.` in ASCII. `en-orig` is YouTube's ORIGINAL track and `en` is
its machine translation into English, so the accident happens to be right and would stop
being right the day a file is named differently. This repository's own cache holds both.

Reported by an external review as undocumented media-file precedence.
"""
from __future__ import annotations

from pathlib import Path

from winnow.media import find_media_file, transcript_for, transcript_source

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
this line came from the subtitle file
"""


def test_a_hand_written_transcript_beats_fetched_captions(tmp_path: Path):
    (tmp_path / "video.en-orig.vtt").write_text(VTT, encoding="utf-8")
    (tmp_path / "transcript.txt").write_text("this line came from transcript.txt", "utf-8")

    assert transcript_for(tmp_path) == "this line came from transcript.txt", (
        "the file the user made by hand lost to the one the fetch left behind, which is "
        "the documented way to fix bad captions and it does nothing"
    )


def test_a_markdown_transcript_beats_fetched_captions(tmp_path: Path):
    (tmp_path / "video.en.vtt").write_text(VTT, encoding="utf-8")
    (tmp_path / "transcript.md").write_text("this line came from transcript.md", "utf-8")

    assert transcript_for(tmp_path) == "this line came from transcript.md"


def test_transcript_txt_wins_over_transcript_md(tmp_path: Path):
    """Both hand-made, so the tie needs a rule rather than a filesystem order."""
    (tmp_path / "transcript.md").write_text("markdown", encoding="utf-8")
    (tmp_path / "transcript.txt").write_text("plain text", encoding="utf-8")

    assert transcript_for(tmp_path) == "plain text"


def test_captions_are_still_used_when_that_is_all_there_is(tmp_path: Path):
    """The guard: preferring the hand-written file must not disable the common case."""
    (tmp_path / "video.en-orig.vtt").write_text(VTT, encoding="utf-8")

    assert transcript_for(tmp_path) == "this line came from the subtitle file"


def test_the_original_caption_track_beats_the_translation(tmp_path: Path):
    """Deliberately, not because `-` sorts before `.`.

    The names here are chosen so alphabetical order points at the WRONG file: `a.en.vtt`
    sorts before `z.en-orig.vtt`. `en` is YouTube's machine translation into English and
    `en-orig` is what was actually said.
    """
    (tmp_path / "a.en.vtt").write_text(
        VTT.replace("the subtitle file", "the TRANSLATED track"), encoding="utf-8"
    )
    (tmp_path / "z.en-orig.vtt").write_text(
        VTT.replace("the subtitle file", "the ORIGINAL track"), encoding="utf-8"
    )

    text = transcript_for(tmp_path)
    assert "ORIGINAL" in text, (
        f"the machine translation won because its filename sorts first: {text!r}"
    )


def test_orig_must_be_the_language_tag_not_a_word_in_the_title(tmp_path: Path):
    """`my-original-talk.vtt` is not an original caption track.

    The marker is the LAST dot-separated part of the stem, which is where yt-dlp puts the
    language tag. A substring test would match any title containing the letters.
    """
    (tmp_path / "a-original-notes.vtt").write_text(
        VTT.replace("the subtitle file", "a title with the word original in it"),
        encoding="utf-8",
    )
    (tmp_path / "z.en-orig.vtt").write_text(
        VTT.replace("the subtitle file", "the ORIGINAL track"), encoding="utf-8"
    )

    text = transcript_for(tmp_path)
    assert "ORIGINAL" in text, (
        f"a word in a filename was mistaken for a language tag: {text!r}"
    )


def test_the_chosen_file_can_be_named(tmp_path: Path):
    """A silent choice between two files is the fault underneath all of the above."""
    (tmp_path / "video.en-orig.vtt").write_text(VTT, encoding="utf-8")
    (tmp_path / "transcript.txt").write_text("mine", encoding="utf-8")

    chosen = transcript_source(tmp_path)
    assert chosen is not None and chosen.name == "transcript.txt", (
        f"the caller cannot tell the user which file was read: {chosen}"
    )


def test_nothing_to_read_is_nothing_to_name(tmp_path: Path):
    (tmp_path / "video.mp4").write_bytes(b"\x00")

    assert transcript_source(tmp_path) is None
    assert transcript_for(tmp_path) is None


def test_a_file_target_names_itself(tmp_path: Path):
    talk = tmp_path / "talk.txt"
    talk.write_text("a transcript passed directly", encoding="utf-8")

    assert transcript_source(talk) == talk
    assert transcript_for(talk) == "a transcript passed directly"


def test_a_media_file_is_not_a_transcript(tmp_path: Path):
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"\x00")

    assert transcript_source(media) is None


def test_ingest_says_which_file_it_read(tmp_path: Path, capsys):
    """The choice is only checkable if the run states it."""
    import json

    from winnow.config import Config
    from winnow.pipeline import Pipeline

    packs_root = Path(__file__).resolve().parent.parent / "packs"
    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "video.en-orig.vtt").write_text(VTT, encoding="utf-8")
    (folder / "transcript.txt").write_text("batching raises utilisation", encoding="utf-8")

    class LineClaimsLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            body = prompt.split("SOURCE MATERIAL:")[-1].strip()
            return json.dumps(
                {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
            )

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(tmp_path / "corpus.db"),
            embed_backend="hashing",
            packs_root=str(packs_root),
            ingest_extra_passes=[],
        )
    )
    pipeline.extractor.llm = LineClaimsLLM()
    try:
        pipeline.ingest(folder)
    finally:
        pipeline.close()

    said = "".join(capsys.readouterr())
    assert "transcript.txt" in said, (
        f"the run picked one of two transcripts and did not say which: {said!r}"
    )


def test_the_first_media_file_alphabetically_is_the_one_used(tmp_path: Path):
    """Documented because a folder with two recordings silently uses one of them."""
    (tmp_path / "b.mp4").write_bytes(b"\x00")
    (tmp_path / "a.mkv").write_bytes(b"\x00")

    found = find_media_file(tmp_path)
    assert found is not None and found.name == "a.mkv", f"got {found}"
