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
#
# CASE-SENSITIVE, which it was not. `\bYOUR[_ ]` under `re.IGNORECASE` matches the ordinary
# English word "your", so applied to any prose written in the second person it fires on every
# sentence. That is what made `test_the_readme_clone_url_is_real` a test that could not
# succeed -- and that test was the strict xfail recording the one finding needing a human.
# A template marker is `YOUR_NAME` in capitals; `your notes` is a sentence.
PLACEHOLDER = re.compile(r"<[A-Za-z][A-Za-z0-9 _-]{0,38}>|\bYOUR[_ ]|\bTODO\b|\bFIXME\b")


def test_no_placeholder_survives_into_the_metadata():
    """`<you>`-style placeholders belong in a README draft, never in package metadata."""
    text = PYPROJECT.read_text(encoding="utf-8")
    placeholders = PLACEHOLDER.findall(text)
    assert not placeholders, f"pyproject.toml still holds placeholders: {placeholders}"


def _clone_urls() -> list[str]:
    """Every URL a `git clone` line in the README would fetch from.

    The URL, not the first token: the starter-corpus section shows
    `git clone --depth 1 --filter=blob:none ...`, so `\\S+` after `clone` is `--depth`.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    found = []
    for line in re.findall(r"git clone\s+(.+)", readme):
        for token in line.split():
            if "://" in token:
                found.append(token)
                break
    return found


def test_every_clone_url_in_the_readme_is_real():
    """The install instructions are the first thing anyone runs, so they have to work.

    `git clone https://github.com/<you>/winnow.git` failed for every reader. It was the one
    finding in the review that could not be fixed from inside the repository, and it was
    recorded as a STRICT xfail so that supplying the URL would turn the test green, strict
    would turn green into a failure, and the marker would come off.

    That mechanism never worked. The check applied the metadata placeholder pattern to the
    README, and that pattern matched `<url>` from the usage line and -- under
    `re.IGNORECASE` -- the ordinary word "your", which a README written in the second person
    contains everywhere. The test could not pass however many placeholders were fixed.

    So it asks the question it was always about: does every clone command name a real
    repository?
    """
    urls = _clone_urls()

    assert urls, "the README should tell people how to clone it"
    for url in urls:
        assert "<" not in url and ">" not in url, f"unfilled placeholder in a clone URL: {url}"
        assert url.startswith("https://github.com/"), f"not a GitHub clone URL: {url}"
        owner_repo = url.removeprefix("https://github.com/").removesuffix(".git")
        assert owner_repo.count("/") == 1 and all(owner_repo.split("/")), (
            f"a clone URL needs owner/name: {url}"
        )


def test_the_readme_and_the_metadata_name_the_same_repository():
    """Two places state where this lives. They cannot say different things."""
    clone_urls = {u.removesuffix(".git") for u in _clone_urls()}
    assert len(clone_urls) == 1, f"the README clones from more than one place: {clone_urls}"

    urls = PROJECT.get("urls", {})
    assert urls, "pyproject should carry [project.urls]"

    repository = clone_urls.pop()
    # EVERY GitHub URL, not merely one of them. Pointing `Homepage` somewhere else while
    # `Source` and `Issues` stayed correct passed a test that asked only whether the clone
    # URL appeared SOMEWHERE -- and a Homepage nobody checks is exactly where a stale
    # address survives.
    wrong = {
        name: url
        for name, url in urls.items()
        if "github.com" in url and not url.startswith(repository)
    }
    assert not wrong, (
        f"the README clones {repository} and these point elsewhere: {wrong}"
    )


def test_the_placeholder_pattern_does_not_fire_on_ordinary_english():
    """The defect that made the clone-URL guard unable to pass, recorded as a test.

    `\bYOUR[_ ]` under `re.IGNORECASE` matches the word "your". Applied to a README written
    in the second person it fires on every other sentence, so the check could never go
    green however many placeholders were fixed -- and it was the check standing in for the
    one review finding that needed a human.
    """
    prose = (
        "Your material never leaves by default. Your notes, transcripts and the claims "
        "extracted from them are never transmitted, and your corpus stays where you put it. "
        "Pass `winnow ingest <url>` a link, or a folder of your own."
    )

    assert not PLACEHOLDER.findall(prose.replace("<url>", "a link")), (
        "the pattern matches ordinary English, so any prose check using it can never pass"
    )


def test_the_placeholder_pattern_still_finds_real_placeholders():
    """The mirror: a pattern that matches nothing is worse than one that over-matches."""
    for template in ("<you>", "<your name here>", "YOUR_NAME", "YOUR TOKEN", "TODO", "FIXME"):
        assert PLACEHOLDER.findall(template), f"{template!r} is a placeholder and was missed"


def test_the_package_says_who_wrote_it():
    authors = PROJECT.get("authors", [])
    assert authors, "a published package should say who is behind it"
    assert all(a.get("name") for a in authors), f"an author needs a name: {authors}"
