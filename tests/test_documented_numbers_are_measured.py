"""Numbers in user-facing prose must come from a recorded measurement.

The README's operating-model section once claimed a 25-minute talk cost "roughly three
minutes" and produced "a handful of claims". Measured, the same run took 4.9 minutes and
produced 72 claims. Both errors flattered the tool, which is the direction documentation
errors always seem to go.

Nothing caught it, because nothing connected the prose to any evidence. These tests do:
every headline figure the README quotes must match `experiments/MEASUREMENTS.json`.

What this can and cannot do. It CAN stop a number being invented in prose or drifting away
from the record. It CANNOT verify the record is still true of the current code -- that needs
re-running the measurement, and the file says how each was taken so it can be.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
MEASUREMENTS = json.loads((ROOT / "experiments" / "MEASUREMENTS.json").read_text(encoding="utf-8"))


def test_the_measurements_file_records_how_each_number_was_taken():
    """A figure without provenance is a figure nobody can re-check."""
    for key, block in MEASUREMENTS.items():
        if key.startswith("_"):
            continue
        assert isinstance(block, dict), f"{key} should be a block, not a bare value"
        assert block.get("how"), f"{key} does not say how it was measured"


def test_the_measurements_file_states_its_hardware_and_models():
    """The same run on other hardware will differ; the figures mean nothing without it."""
    assert MEASUREMENTS["_hardware"]
    assert MEASUREMENTS["_models"]["extraction"]
    assert "order of magnitude" in MEASUREMENTS["_caveat"]


def test_the_readme_quotes_the_measured_ingest_time():
    minutes = MEASUREMENTS["spoken_talk_ingest"]["minutes"]
    assert f"{minutes}" in README, (
        f"README should quote the measured {minutes} minutes, not a remembered figure"
    )


def test_the_readme_quotes_the_measured_claim_count():
    claims = MEASUREMENTS["spoken_talk_ingest"]["claims"]
    assert f"{claims} claims" in README, f"README should quote the measured {claims} claims"


def test_the_readme_does_not_minimise_the_output_count():
    """It was 72. Calling that 'a handful' is the flattery this file exists to stop.

    Checked case-insensitively and across a line break, because the first version of this
    test matched one exact lowercase phrase and a capitalised variant walked straight
    through it.
    """
    claims = MEASUREMENTS["spoken_talk_ingest"]["claims"]
    flat = " ".join(README.split()).lower()

    for phrase in ("a handful of claims", "a few claims", "just a few claims", "a couple of claims"):
        assert phrase not in flat, (
            f"the README calls the output {phrase!r}, but the measured count is {claims}"
        )


def test_the_readme_admits_a_fresh_corpus_sorts_nothing():
    """Every one of those 72 came back `?`. A first run is corpus-building, not judging."""
    assert "fresh corpus" in README
    assert "`?`" in README


@pytest.mark.parametrize(
    "figure",
    [
        "0.039",  # ms per stored claim per comparison
        "88",  # percent faithful, hand-graded
    ],
)
def test_figures_quoted_in_docs_appear_in_the_record(figure):
    """Spot-check that headline numbers used across the docs are recorded somewhere."""
    recorded = json.dumps(MEASUREMENTS)
    assert figure in recorded, f"{figure} is quoted in the docs but not recorded"


def test_no_documentation_figure_claims_more_precision_than_a_single_run_supports():
    """One run on one machine does not justify three decimal places."""
    stated = MEASUREMENTS["spoken_talk_ingest"]["minutes"]
    assert len(str(stated).split(".")[-1]) <= 1, (
        "a single wall-clock run supports one decimal place at most"
    )


def test_the_caveat_survives_in_the_readme():
    """A measured number without its conditions invites being read as a specification."""
    assert re.search(r"12\s*GB consumer GPU|consumer GPU", README), (
        "the README should say what hardware the figure came from"
    )
