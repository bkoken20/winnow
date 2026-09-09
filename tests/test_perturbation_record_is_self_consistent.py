"""The perturbation record must agree with its own tables.

Its header said "26 behaviours, over five rounds" while the tables below held 48 numbered
rows across eleven rounds. The README said forty-eight and was right.

The existing count-sync test compares the README against the ROW COUNT, so it passed
throughout: it had never been asked to read this document's own summary of itself. A file
whose subject is checking claims carried an unchecked one in its opening paragraph.

Reported by an external review.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERTURBATION = (ROOT / "tests" / "PERTURBATION.md").read_text(encoding="utf-8")

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15,
}


def _rows() -> int:
    return len(re.findall(r"^\| \d+ \|", PERTURBATION, re.MULTILINE))


def _rounds() -> int:
    return len(re.findall(r"^## Round ", PERTURBATION, re.MULTILINE))


def test_the_document_holds_rows_and_rounds():
    """Guard the guard: if either pattern stops matching, everything below passes."""
    assert _rows() > 10, f"only found {_rows()} numbered rows"
    assert _rounds() > 3, f"only found {_rounds()} round headings"


def test_the_stated_behaviour_count_matches_the_tables():
    stated = re.search(r"\*\*(\d+) behaviours", PERTURBATION)
    assert stated, "the summary should state how many behaviours the tables record"
    assert int(stated.group(1)) == _rows(), (
        f"the summary says {stated.group(1)} behaviours; the tables hold {_rows()} rows"
    )


def test_the_stated_round_count_matches_the_headings():
    stated = re.search(r"behaviours, over ([a-z]+) rounds", PERTURBATION)
    assert stated, "the summary should state how many rounds there were"
    word = stated.group(1)
    assert word in _WORDS, f"unrecognised number word {word!r}"
    assert _WORDS[word] == _rounds(), (
        f"the summary says {word} ({_WORDS[word]}) rounds; there are {_rounds()} headings"
    )


def test_the_rows_are_numbered_without_gaps_or_repeats():
    """A count is only meaningful if the rows it counts are a clean sequence."""
    numbers = [int(n) for n in re.findall(r"^\| (\d+) \|", PERTURBATION, re.MULTILINE)]
    assert numbers == sorted(numbers), f"row numbers are out of order: {numbers}"
    assert len(set(numbers)) == len(numbers), "a row number is used twice"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"row numbers run {numbers[0]}..{numbers[-1]} with {len(numbers)} rows -- there is a "
        "gap or a duplicate"
    )
