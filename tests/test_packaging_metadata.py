"""pyproject.toml is a claim about how to install and run this, and nothing checked it.

The `dev` extra promised the development dependencies and listed only pytest. requirements.txt
lists pytest AND pyflakes, and the README says so. Someone following `pip install -e .[dev]`
therefore got a suite where `test_no_undefined_names_or_unused_imports` -- the check that
catches undefined names in files no test imports, which is the whole reason it exists -- is
skipped by its own skipif, silently, showing as a single `s` in a `-q` run.

A missing dependency that degrades a check into a skip is worse than one that fails: the
suite still reports green.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"


def _toml() -> dict:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    # requires-python is >=3.10, so this file must parse without tomllib too.
    text = PYPROJECT.read_text(encoding="utf-8")
    dev = re.search(r"dev\s*=\s*\[(.*?)\]", text, re.DOTALL)
    return {
        "project": {
            "optional-dependencies": {
                "dev": re.findall(r'"([^"]+)"', dev.group(1)) if dev else []
            },
            "requires-python": re.search(r'requires-python\s*=\s*"([^"]+)"', text).group(1),
            "description": re.search(r'description\s*=\s*"([^"]+)"', text).group(1),
        }
    }


def _names(specs) -> set[str]:
    return {re.split(r"[<>=!~\[]", s.strip())[0].lower() for s in specs if s.strip()}


def test_the_dev_extra_installs_what_the_suite_needs():
    dev = _names(_toml()["project"]["optional-dependencies"]["dev"])
    required = _names(REQUIREMENTS.read_text(encoding="utf-8").splitlines())
    missing = sorted(required - dev)
    assert not missing, (
        f"pip install -e .[dev] does not install {missing}, which requirements.txt and the "
        "README both list. Without pyflakes the undefined-name check does not fail -- it "
        "SKIPS, and the suite still reports green."
    )


def test_the_readme_install_block_matches_requirements():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = _names(REQUIREMENTS.read_text(encoding="utf-8").splitlines())
    for name in required:
        assert name in readme.lower(), f"{name} is required to run the tests but the README never names it"


def test_the_declared_python_floor_is_one_this_code_could_run_on():
    """A floor nothing enforces is still a claim; keep it honest about syntax, at least.

    This does NOT prove the code runs on 3.10 -- only an interpreter can do that, and there
    is not one here. It catches the cheap half: syntax and stdlib introduced later.
    """
    floor = _toml()["project"]["requires-python"]
    assert floor.startswith(">=3."), floor
    major_minor = tuple(int(p) for p in floor.removeprefix(">=").split("."))

    # Keyed by the version that INTRODUCED each construct, so the check bites at whatever
    # floor is declared rather than at one particular number.
    introduced_in = {
        (3, 10): re.compile(r"^\s*match .*:\s*$|slots=True", re.MULTILINE),
        (3, 11): re.compile(r"\bexcept\*|\btomllib\b|datetime\.UTC\b|\bLiteralString\b"),
        (3, 12): re.compile(r"^\s*type [A-Za-z_]\w*\s*=", re.MULTILINE),
    }
    offenders = []
    for path in sorted((ROOT / "winnow").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for version, pattern in introduced_in.items():
            if version > major_minor and pattern.search(text):
                offenders.append(f"{path.name} uses something added in {version[0]}.{version[1]}")
    assert not offenders, (
        f"declared floor is {floor}, but: {offenders}"
    )
