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


def _tested_pythons() -> set[str]:
    return {
        str(v)
        for job in _workflow()["jobs"].values()
        for v in job.get("strategy", {}).get("matrix", {}).get("python-version", [])
    }


def test_it_tests_the_oldest_python_the_package_claims():
    """`requires-python` is a promise. CI is the only thing that can keep it."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    floor = re.search(r'requires-python\s*=\s*">=\s*([\d.]+)"', pyproject).group(1)

    tested = _tested_pythons()
    assert tested, "no Python version matrix at all"
    assert floor in tested, (
        f"pyproject promises Python {floor} and CI tests {sorted(tested)}"
    )


def test_it_tests_every_python_the_classifiers_advertise():
    """A classifier is a claim made to a stranger reading the package listing.

    This checked only the FLOOR, so the classifiers were free to say anything: they
    advertised 3.10, 3.11, 3.12 and 3.13 while CI ran two of them. Either the version is
    tested or it is not claimed -- the same rule the rest of this repository lives by.
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    claimed = set(
        re.findall(r"Programming Language :: Python :: (\d+\.\d+)", pyproject)
    )
    assert claimed, "the classifiers should say which Pythons this is for"

    untested = sorted(claimed - _tested_pythons(), key=lambda v: tuple(map(int, v.split("."))))
    assert not untested, (
        f"the package advertises Python {untested} and CI has never run "
        f"{'them' if len(untested) > 1 else 'it'}"
    )


def test_a_commit_is_not_tested_twice():
    """A branch pushed and then opened as a pull request triggers both events.

    The second run answers a question the first already answered, and on a matrix of eight
    jobs that is eight duplicate jobs. A concurrency group cancels the superseded run --
    what is wanted is the answer about the NEWEST commit, not every commit.
    """
    concurrency = _workflow().get("concurrency")

    assert concurrency, "push and pull_request both fire, so the same commit is tested twice"
    assert "github.ref" in str(concurrency.get("group", "")), (
        "the group must be per-branch, or one branch's run cancels another's"
    )
    assert concurrency.get("cancel-in-progress") is True


@pytest.mark.parametrize("job", ["test", "build"])
def test_every_job_is_bounded(job):
    """GitHub's default is SIX HOURS. A job hung on a network wait would sit there.

    The same reasoning as `fetch_timeout_seconds`: this bounds a hang, it is not tight. The
    suite runs offline in about a minute.
    """
    limit = _workflow()["jobs"][job].get("timeout-minutes")

    assert limit, f"the {job} job has no timeout, so it inherits GitHub's six hours"
    assert limit <= 30, f"{limit} minutes is not a bound on a one-minute suite"


def test_the_packaging_tools_are_pinned():
    """An unpinned build tool means the packaging check can break on a day nothing changed.

    A green suite that goes red because someone else released is a false alarm, and false
    alarms are how a check stops being read.
    """
    commands = _commands()

    for tool in ("build", "twine"):
        assert re.search(rf'"{tool}==[\d.]+', commands), (
            f"{tool} is installed unpinned, so CI depends on whatever was released today"
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
