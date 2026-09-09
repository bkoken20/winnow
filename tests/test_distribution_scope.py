"""The wheel excludes the packs, and nothing said so out loud.

`[tool.setuptools.packages.find] include = ["winnow*"]` leaves `packs/` out of the built
distribution. So `pip install winnow` produces a tool that exits 1 with "no domain packs
found" -- broken by design, and the design is right: Winnow needs a model server, models and
optionally ffmpeg, so a package install could never produce a working tool on its own.

What was missing is the sentence. The README said "distributed by clone, not as a package"
in one place and CI built a wheel and ran `twine check` on it in another, with nothing
stating whether a package release is intended. A reader could reasonably conclude a PyPI
upload was planned and that the missing packs were an oversight.

Operator decision, 2026-09-09: **PyPI is out of scope.** The wheel is a check on the metadata
that `pip install -e .` depends on, not a product.

This test ties the two together in both directions, so the day the packaging changes the
statement has to change with it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _toml() -> dict:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    import tomli

    return tomli.loads(PYPROJECT.read_text(encoding="utf-8"))


def _releasing() -> str:
    start = README.index("## Releasing")
    end = README.index("\n## ", start + 1)
    return README[start:end]


def _wheel_carries_packs() -> bool:
    find = _toml().get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
    patterns = find.get("include", [])
    return any(p.startswith("packs") for p in patterns)


def test_the_packaging_and_the_statement_agree():
    """Both directions. Include the packs one day and this asks you to rewrite the section."""
    carries = _wheel_carries_packs()
    declared_out_of_scope = "PyPI" in _releasing()

    assert carries != declared_out_of_scope, (
        "the wheel carries the packs but Releasing still says a package install is not the "
        "distribution"
        if carries
        else "the wheel leaves the packs out, so `pip install winnow` cannot work -- the "
        "Releasing section has to say that a package release is not intended"
    )


def test_the_reason_is_given_not_just_the_ruling():
    """A scope decision with no reason is one somebody reverses next year."""
    section = _releasing().lower()

    assert "packs" in section, "say what a package install would be missing"
    assert "pip install -e ." in section or "clone" in section, (
        "say what the supported install is instead"
    )


def test_ci_still_builds_because_the_documented_install_depends_on_it():
    """The build job is not vestigial: `pip install -e .` reads the same metadata.

    Worth stating, because "PyPI is out of scope" is exactly the reasoning someone would use
    to delete the job, and then a broken `pyproject.toml` would reach a user through the
    install the README actually tells them to run.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "python -m build" in workflow
    assert re.search(r"pip install -e", workflow), (
        "CI must exercise the install the README documents"
    )
