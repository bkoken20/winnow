"""There is no CI, so nothing has ever run this suite on a machine that is not mine.

Every claim the repository makes about Python 3.10 is untested: `requires-python = ">=3.10"`,
the classifiers, and a test in test_packaging_metadata.py that says outright it "does NOT
prove the code runs on 3.10 -- only an interpreter can do that, and there is not one here."

The same gap covers the operating system. Winnow was written on Windows and carries
Windows-shaped code -- console code pages, path spelling, `PermissionError` where another
system raises `IsADirectoryError`.

A workflow file is itself a claim, so this checks the things about it that can be checked
from here: that it parses, that it runs the suite the README documents, and that the Python
it tests is the one the package promises.

Reported by an external review.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return [
        step
        for job in _workflow()["jobs"].values()
        for step in job.get("steps", [])
    ]


def _commands() -> str:
    return "\n".join(step.get("run", "") for step in _steps())


def test_there_is_a_workflow_and_it_parses():
    assert WORKFLOW.exists(), f"{WORKFLOW.relative_to(ROOT)} does not exist"
    assert _workflow().get("jobs"), "a workflow with no jobs runs nothing"


def test_it_tests_the_oldest_python_the_package_claims():
    """`requires-python` is a promise. CI is the only thing that can keep it."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    floor = re.search(r'requires-python\s*=\s*">=\s*([\d.]+)"', pyproject).group(1)

    tested = {
        str(v)
        for job in _workflow()["jobs"].values()
        for v in job.get("strategy", {}).get("matrix", {}).get("python-version", [])
    }
    assert tested, "no Python version matrix at all"
    assert floor in tested, (
        f"pyproject promises Python {floor} and CI tests {sorted(tested)}"
    )


def test_it_tests_more_than_one_python():
    tested = {
        str(v)
        for job in _workflow()["jobs"].values()
        for v in job.get("strategy", {}).get("matrix", {}).get("python-version", [])
    }
    assert len(tested) >= 2, f"one version proves nothing about a range: {sorted(tested)}"


def test_it_runs_the_suite_the_readme_documents():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m pytest tests/" in readme, "the README's test command changed"
    assert "pytest tests/" in _commands(), (
        "CI must run the same suite the README tells a contributor to run"
    )


def test_it_runs_the_linter_that_catches_undefined_names():
    assert "pyflakes" in _commands(), (
        "pyflakes finds undefined names in files no test imports, which is the whole "
        "reason the suite shells out to it"
    )


def test_it_builds_the_distribution_it_publishes_metadata_for():
    commands = _commands()
    assert "build" in commands, "nothing checks that the package still builds"
    assert "twine check" in commands, (
        "the metadata added for a listing page is only real if something validates it"
    )


@pytest.mark.parametrize("action", ["actions/checkout", "actions/setup-python"])
def test_every_action_is_pinned_to_a_major_version(action):
    """An unpinned action is a third party changing your CI without telling you."""
    used = [step["uses"] for step in _steps() if "uses" in step]
    matching = [u for u in used if u.startswith(action)]

    assert matching, f"{action} is not used at all"
    for entry in matching:
        assert "@" in entry, f"{entry} has no version"
        assert entry.split("@", 1)[1] not in ("main", "master"), (
            f"{entry} follows a moving branch"
        )
