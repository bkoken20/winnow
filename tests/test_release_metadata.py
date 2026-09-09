"""What `pip install winnow` would tell people, and whether it is true.

Two separate faults.

**The version can drift.** `winnow/__init__.py` and `pyproject.toml` each state a version and
nothing compared them. A package whose installed metadata disagrees with `winnow.__version__`
makes every bug report ambiguous, and the drift is invisible until someone reads both files.

**The metadata is thin.** No classifiers, no keywords, and a `license = {file = ...}` table
that setuptools 77+ deprecates in favour of the PEP 639 SPDX string. None of that changes
what the tool does; all of it is what a listing page shows and what tooling reads.

Reported by an external review.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _toml() -> dict:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    import tomli

    return tomli.loads(PYPROJECT.read_text(encoding="utf-8"))


PROJECT = _toml()["project"]


def test_the_two_declared_versions_agree():
    declared = PROJECT["version"]
    init = (ROOT / "winnow" / "__init__.py").read_text(encoding="utf-8")
    in_code = re.search(r'__version__\s*=\s*"([^"]+)"', init)

    assert in_code, "winnow/__init__.py should declare __version__"
    assert in_code.group(1) == declared, (
        f"pyproject.toml says {declared}, winnow/__init__.py says {in_code.group(1)}"
    )


def test_the_installed_package_reports_the_same_version():
    """The guarantee is about what an INSTALLED copy says, not two files agreeing."""
    import winnow

    assert winnow.__version__ == PROJECT["version"]


def test_the_licence_is_declared_the_modern_way():
    """PEP 639: an SPDX string. The `{file = ...}` table is deprecated in setuptools 77+."""
    licence = PROJECT.get("license")

    assert isinstance(licence, str), (
        f"license should be an SPDX expression such as \"MIT\", got {licence!r}"
    )
    assert licence == "MIT", f"the repository ships an MIT LICENSE; metadata says {licence!r}"
    assert "LICENSE" in PROJECT.get("license-files", []), (
        "license-files should ship the LICENSE file that license= names"
    )


def test_there_are_classifiers_and_they_do_not_contradict_requires_python():
    classifiers = PROJECT.get("classifiers", [])
    assert classifiers, "a published package should carry trove classifiers"

    floor = tuple(
        int(part)
        for part in re.search(r">=\s*(\d+)\.(\d+)", PROJECT["requires-python"]).groups()
    )
    versions = [
        tuple(int(p) for p in m.groups())
        for m in (
            re.fullmatch(r"Programming Language :: Python :: (\d+)\.(\d+)", c)
            for c in classifiers
        )
        if m
    ]
    assert versions, "say which Python versions this is for"
    too_old = [v for v in versions if v < floor]
    assert not too_old, (
        f"classifiers claim Python {too_old} but requires-python is "
        f"{PROJECT['requires-python']}"
    )


def test_a_typed_claim_ships_the_marker_that_makes_it_true():
    """`Typing :: Typed` tells a type checker to read this package's annotations.

    What a checker actually reads is `winnow/py.typed`. The classifier without the file is a
    promise to tooling that the tooling then cannot act on, so the two move together or not
    at all.
    """
    claims_typed = "Typing :: Typed" in PROJECT.get("classifiers", [])
    has_marker = (ROOT / "winnow" / "py.typed").exists()

    assert claims_typed == has_marker, (
        "classifiers claim Typing :: Typed and winnow/py.typed does not exist, so no type "
        "checker will read the annotations the classifier advertises -- add the marker or "
        "drop the classifier"
        if claims_typed
        else "winnow/py.typed exists but no classifier tells anyone to look for it"
    )


def test_the_keywords_describe_what_it_is():
    keywords = PROJECT.get("keywords", [])
    assert keywords, "a package nobody can search for is a package nobody finds"
    assert len(keywords) >= 4, f"too few to be useful: {keywords}"


# Angle-bracket text starting with a letter, plus the usual words. Deliberately not
# `<[a-z-]+>`, which was the first spelling and let `<your keyword here>` through -- no
# spaces, no capitals. The leading-letter rule keeps `python_version < '3.11'` out of it.
PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 _-]{0,38}>|\bYOUR[_ ]|\bTODO\b|\bFIXME\b",
                         re.IGNORECASE)


def test_no_placeholder_survives_into_the_metadata():
    """`<you>`-style placeholders belong in a README draft, never in package metadata."""
    text = PYPROJECT.read_text(encoding="utf-8")
    placeholders = PLACEHOLDER.findall(text)
    assert not placeholders, f"pyproject.toml still holds placeholders: {placeholders}"


@pytest.mark.xfail(
    strict=True,
    reason="review item 14: the clone URL is not ours to invent -- it needs the real "
           "repository. When one exists and the README is updated, this test passes, the "
           "strict marker turns that into a failure, and the marker comes off.",
)
def test_the_readme_clone_url_is_real():
    """The install instructions are the first thing anyone runs, and they cannot work.

    `git clone https://github.com/<you>/winnow.git` fails for every reader. This is the one
    finding in the review that cannot be fixed from inside the repository, so it is recorded
    where it cannot be forgotten rather than in a note.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    placeholders = PLACEHOLDER.findall(readme)
    assert not placeholders, f"README still holds placeholders: {sorted(set(placeholders))}"
