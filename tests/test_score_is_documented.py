"""The score, and the three cutoffs on it, must stay documented and stay correct.

The number beside every verdict is the most visible thing Winnow prints, and it was
explained nowhere: the README showed it four times without a word, and the cutoffs lived in
two disconnected parts of PARAMETERS.md with nothing saying they measure the same quantity.

Documenting it once is not enough. The cutoffs are constants in the code, so the prose can
go stale the moment one of them moves -- silently, and in the direction that matters, since
a reader tuning `duplicate_threshold` is reading the page precisely because they cannot see
the constants. These tests tie the prose to the values it describes.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from winnow.config import Config
from winnow.judge import SIMILARITY_KNOWN, SIMILARITY_VARIANT

ROOT = Path(__file__).resolve().parent.parent
PARAMETERS = (ROOT / "docs" / "PARAMETERS.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    body = text.split(f"\n## {heading}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def test_the_score_has_a_section_of_its_own():
    assert "\n## Reading the score\n" in PARAMETERS, (
        "the number printed beside every verdict needs somewhere to be explained"
    )


def test_the_section_says_which_way_the_score_runs():
    """A similarity score beside the word NEW reads backwards unless you say so."""
    section = _section(PARAMETERS, "Reading the score").lower()
    assert "cosine" in section, "say what the number is"
    assert "higher" in section, "say which direction means 'already known'"
    assert "not a confidence" in section or "not a novelty score" in section, (
        "say explicitly what it is NOT; a bare 0-1 number is read as confidence"
    )


def test_every_cutoff_in_the_prose_matches_the_code():
    """The prose quotes three numbers. All three live in the code, and can move."""
    section = _section(PARAMETERS, "Reading the score")
    duplicate = dataclasses.fields(Config)
    default_duplicate = next(
        f.default for f in duplicate if f.name == "duplicate_threshold"
    )

    for value, name in (
        (SIMILARITY_VARIANT, "SIMILARITY_VARIANT"),
        (SIMILARITY_KNOWN, "SIMILARITY_KNOWN"),
        (default_duplicate, "duplicate_threshold"),
    ):
        assert f"{value:.2f}" in section, (
            f"{name} is {value}, and that number does not appear in the section that "
            "explains the cutoffs -- the prose has drifted from the code"
        )


def test_the_ordering_of_the_two_upper_cutoffs_is_explained():
    """0.93 > 0.90 creates a band where a claim is called known and still stored.

    That is surprising, so it has to be stated rather than left for someone to infer from
    two numbers in different rows.
    """
    assert SIMILARITY_KNOWN < Config().duplicate_threshold, (
        "this test's premise is that suppression sits ABOVE the known cutoff; if that "
        "changed, the documentation needs rewriting rather than this test relaxing"
    )
    section = _section(PARAMETERS, "Reading the score").lower()
    assert "still" in section and "kept" in section or "still be kept" in section, (
        "the band between the known cutoff and the suppression cutoff must be described"
    )


def test_the_readme_explains_the_number_where_it_first_shows_one():
    """A reader meets the score in the example output, long before PARAMETERS.md."""
    before_quickstart = README.split("## Quickstart")[0].lower()
    assert "[new" in before_quickstart, "the example output should still be there"
    assert "higher means you have seen it before" in before_quickstart, (
        "the example prints the score four times; the direction has to be given there, "
        "not only in a page the reader has not opened yet"
    )


def test_the_thresholds_are_tied_to_the_embedding_model():
    """They are calibrated for one embedder and mean something else under another."""
    section = _section(PARAMETERS, "Reading the score")
    assert Config().embed_model in section, (
        "the cutoffs are only meaningful for the embedding model they were chosen for; "
        "say which one"
    )
