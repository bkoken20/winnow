"""The perturbation record must agree with its own tables, and with the CURRENT claim.

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

_UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
         "ninety"]


def _number_words(high: int = 99) -> dict[str, int]:
    """Generated, not listed.

    The literal dict this replaces stopped at fifteen, and round sixteen then failed a test
    about the RECORD for a reason that had nothing to do with the record -- the same fault
    `test_docs_match_code._number_words` was written to end, one file over.
    """
    words = {}
    for n in range(1, min(high, 99) + 1):
        if n < 20:
            words[_UNITS[n]] = n
        else:
            tens, unit = divmod(n, 10)
            words[_TENS[tens] + (f"-{_UNITS[unit]}" if unit else "")] = n
    return words


_WORDS = _number_words()


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
    # Anchored on the BOLD summary line, and allowing a hyphen.
    #
    # It was `r"behaviours, over ([a-z]+) rounds"`, unanchored. `[a-z]+` cannot match
    # "twenty-one", so the search slid down the document and matched the parenthetical that
    # quotes the old wrong line -- "26 behaviours, over five rounds" -- then reported the
    # summary as saying five. This document exists to record claims that were wrong, so it
    # will always contain quoted wrong claims; a loose search over it will keep finding them.
    stated = re.search(r"\*\*\d+ behaviours, over ([a-z-]+) rounds\.\*\*", PERTURBATION)
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
