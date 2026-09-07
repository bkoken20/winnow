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
import pathlib
import re
from pathlib import Path


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


# Numbers that are not measurements of this tool: version strings, the similarity
# thresholds documented in PARAMETERS.md, ordinary counts in prose. Each is listed with why,
# because an exemption nobody has to justify is how the check stops covering anything.
NOT_MEASUREMENTS = {
    "0.1": "version",
    "3.10": "the Python floor",
    "2.5": "model names (qwen2.5)",
    "11434": "the Ollama port",
    "720": "video height cap",
    "640": "frame downscale width",
    "80": "a --limit value the reader types, not a measured quantity",
    "15": "an --accept-minutes value the reader types",
    "25": "min_corpus, a configured threshold",
    "1000": "a chunk size, configured",
    "2000": "a chunk size, configured",
    "4000": "a chunk size, configured",
    "7": "model size in qwen2.5vl:7b",
    "14": "model size in qwen2.5:14b, and the quickstart's total minutes",
    "3": "counts in prose (three models, three passes)",
    "42": "the perturbation count, checked against PERTURBATION.md by its own test",
}


def _quantities_in(text: str) -> set[str]:
    """Every number the README attaches to a unit or a percent -- i.e. a measured quantity.

    Bare integers in prose are not claims about measurement; "4.9 minutes" and "92%" are.
    """
    pattern = r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:%|minutes?|hours?|seconds?|files?|claims?|KB|MB|GB)\b"
    found = set()
    for raw in re.findall(pattern, text):
        value = raw.replace(",", "")
        if value not in NOT_MEASUREMENTS:
            found.add(value)
    return found


def _live_record() -> str:
    """The recorded figures, as searchable text.

    Commas are stripped because prose writes "10,000 claims" and the record writes the same
    thing -- the extractor normalises one side, so it has to normalise the other. That
    mismatch reported a recorded figure as missing.

    Blocks marked NOT MEASURED are excluded: such a block quotes the withdrawn figure in
    order to withdraw it, which would otherwise make the withdrawn number pass this check.
    """
    live = {
        key: block for key, block in MEASUREMENTS.items()
        if not (isinstance(block, dict) and "NOT MEASURED" in str(block.get("status", "")))
    }
    return json.dumps(live).replace(",", "")


def test_every_measured_quantity_in_the_readme_is_recorded():
    """Extracted, not enumerated.

    The previous version of this test listed three figures by hand and called itself a
    spot-check. A spot-check of three cannot catch the fourth, and did not: '96-100%' stood
    until the README was read against the table it summarised, and '337 files / 3.5 hours'
    sat in the Quickstart -- the figure that tells someone whether to commit to an overnight
    job -- with nothing recording where it came from.
    """
    # Only LIVE measurements count. A block recording that a figure was withdrawn quotes
    # that figure in order to say so, which would otherwise make the withdrawn number pass
    # this very check -- found by re-adding "337 files, about 3.5 hours" to the README after
    # the withdrawal was recorded, and watching it sail through.
    recorded = _live_record()
    missing = sorted(q for q in _quantities_in(README) if q not in recorded)
    assert not missing, (
        f"quantities quoted in the README with no entry in MEASUREMENTS.json: {missing}. "
        "That file's whole purpose is that numbers in prose come from it."
    )


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


def _tracked_docs() -> list[pathlib.Path]:
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "*.md", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(out) > 20, f"expected a substantial listing, got {out}"
    return [ROOT / rel for rel in out]


def test_every_measured_quantity_in_the_docs_is_recorded():
    """The same question as the README test, asked of docs/ as well.

    docs/ carried two unrecorded figures while the README carried none, because the check
    only ever looked at the README.
    """
    recorded = _live_record()
    missing = {}
    for path in sorted((ROOT / "docs").glob("*.md")):
        gap = sorted(q for q in _quantities_in(path.read_text(encoding="utf-8"))
                     if q not in recorded)
        if gap:
            missing[path.name] = gap
    assert not missing, f"quantities in docs/ with no entry in MEASUREMENTS.json: {missing}"


def _projected_figures() -> dict[str, str]:
    """Figures recorded as PROJECTIONS rather than measured runs, as {figure: block name}."""
    out = {}
    for key, block in MEASUREMENTS.items():
        if not isinstance(block, dict):
            continue
        if "PROJECTED" not in str(block.get("status", "")).upper():
            continue
        for figure in block.get("figures", []):
            out[str(figure)] = key
    return out


def test_a_projection_is_never_quoted_as_a_measurement():
    """Wherever a projected figure appears, the paragraph around it must say so.

    TWO_PASS.md states that its index hours are projected from throughput and are not a
    measured run. The same hours were quoted in five other files with no caveat, where they
    read as a measurement -- which is the whole reason the caveat was written.
    """
    projected = _projected_figures()
    assert projected, "no projected figures recorded; this check would pass vacuously"

    marks = ("project", "not a measured", "not measured", "extrapolat", "estimate")
    offenders = []
    for path in _tracked_docs():
        if path.name == "MEASUREMENTS.json":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # A WINDOW around each occurrence, not the enclosing paragraph. Paragraph
        # granularity passed for the wrong reason at two of four perturbed sites: a markdown
        # table is one block, so "The projection accounts for it" in an unrelated row
        # satisfied a different row, and config.py's dataclass comments are one block, so
        # "NOT measured" written about frame sampling satisfied a claim about index hours.
        for figure in projected:
            start = 0
            while (index := text.find(figure, start)) != -1:
                start = index + len(figure)
                window = text[max(0, index - 240):index + 240].lower()
                if not any(mark in window for mark in marks):
                    rel = path.relative_to(ROOT).as_posix()
                    line = text.count("\n", 0, index) + 1
                    offenders.append(
                        f"{rel}:{line}: {figure!r} quoted with no mark of a projection"
                    )
    assert not offenders, (
        "projected figures presented as measurements:\n  " + "\n  ".join(sorted(set(offenders)))
    )
