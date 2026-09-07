"""The shipped reference grades belong to one specific transcript.

`correctness_reference_grades.json` holds 25 verdicts keyed "0".."24" -- positions in a
blind sample drawn from the author's transcript. `strict_judge_study.py` used to join them
to whatever claims the current run extracted, by that position.

Point the studies at your own transcript, as experiments/README.md tells you to, and the
join is nonsense: verdict 7 of the author's sample compared against your claim 7, printed as
"agreement with hand grades: 7/25 (28%)" in exactly the format of the published figure, with
no warning that the two sides describe different sentences.

(The file was called correctness_human_grades.json when this was written. Renaming it was
part of the fix: its own `grader` field names a frontier model.)

A number that is silently wrong is worse than no number, and this repo's own experiments
exist to make that point about model judges. It applies to the harness too.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "experiments"
STRICT = EXPERIMENTS / "strict_judge_study.py"


def _grades_file() -> Path:
    """The reference grades, whatever they end up being called."""
    matches = sorted(EXPERIMENTS.glob("correctness_*grades.json"))
    assert len(matches) == 1, f"expected exactly one reference-grades file, found {matches}"
    return matches[0]


def test_the_reference_grades_say_which_source_they_belong_to():
    """Positional verdicts are only meaningful against the sample they were drawn from."""
    data = json.loads(_grades_file().read_text(encoding="utf-8"))
    assert data.get("applies_to"), (
        "the grades are keyed by position, so the file must say which sample those "
        "positions index; without that nothing stops them being joined to another run"
    )


def test_the_grades_file_is_not_named_after_a_grader_it_did_not_have():
    """The file's own `grader` field says a frontier model. The name said human."""
    path = _grades_file()
    grader = json.loads(path.read_text(encoding="utf-8"))["grader"]
    if "human" in path.name.lower():
        assert "human" in grader.lower(), (
            f"{path.name} is named for human grading but records grader={grader!r}"
        )


def test_the_strict_study_refuses_a_positional_join_it_cannot_verify():
    """It must not compare the shipped grades against claims from a different source."""
    source = STRICT.read_text(encoding="utf-8")
    assert "WINNOW_REFERENCE_GRADES" in source, (
        "strict_judge_study.py joins shipped reference grades to freshly extracted claims "
        "by position and reports the agreement as a finding. It must instead take the "
        "grades for THIS run (WINNOW_REFERENCE_GRADES) and skip the comparison otherwise"
    )


def test_no_experiment_script_calls_its_reference_grades_human():
    """Same misattribution as the docs had, in variable names and printed output."""
    offenders = []
    for path in sorted(EXPERIMENTS.glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Denials ("not by a human") are the correction, not the defect.
            if re.search(r"\bhuman\b", line, re.IGNORECASE) and not re.search(
                r"not\s+(a|by\s+a)\s+human", line, re.IGNORECASE
            ):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "grading was done by a frontier model, not a human:\n" + "\n".join(offenders)
