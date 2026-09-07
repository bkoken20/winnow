"""The documentation must describe the code that exists.

`docs/PARAMETERS.md` was verified by hand once, then drifted within the hour: three config
fields were added and the page was not updated. A check that only runs when someone
remembers is not a check, so it runs here.

This is deliberately narrow. It asserts that every setting is *mentioned*, not that the
prose is accurate -- no test can verify that. It catches the failure that actually happened:
a knob shipping with no documentation at all.
"""

import dataclasses
import json
import re
from pathlib import Path

import pytest

from winnow.config import Config

ROOT = Path(__file__).resolve().parent.parent
PARAMETERS = ROOT / "docs" / "PARAMETERS.md"
README = ROOT / "README.md"
PERTURBATION = ROOT / "tests" / "PERTURBATION.md"


def _backticked(text: str) -> set[str]:
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text))


def test_every_config_setting_is_documented():
    documented = _backticked(PARAMETERS.read_text(encoding="utf-8"))
    fields = {f.name for f in dataclasses.fields(Config)} - {"extra"}
    missing = sorted(fields - documented)
    assert not missing, (
        f"settings absent from docs/PARAMETERS.md: {missing}. "
        "A knob nobody can find is a knob nobody can use."
    )


def test_parameters_page_invents_no_settings():
    """The reverse drift: documenting a setting that was renamed or removed."""
    fields = {f.name for f in dataclasses.fields(Config)}
    doc = PARAMETERS.read_text(encoding="utf-8")
    # Only check names presented as settings in the tables, not prose backticks generally.
    claimed = set(re.findall(r"^\| `([a-z_][a-z0-9_]*)`", doc, re.MULTILINE))
    pack_fields = set(json.loads(
        (ROOT / "packs" / "ai_tooling" / "pack.json").read_text(encoding="utf-8")
    ))
    cli_and_env = {"config", "accept-minutes", "new-only", "WINNOW_NOTES"}
    unknown = sorted(claimed - fields - pack_fields - cli_and_env)
    assert not unknown, f"docs/PARAMETERS.md documents settings that do not exist: {unknown}"


def test_every_pack_field_is_documented():
    documented = _backticked(PARAMETERS.read_text(encoding="utf-8"))
    pack = json.loads((ROOT / "packs" / "ai_tooling" / "pack.json").read_text(encoding="utf-8"))
    missing = sorted(set(pack) - documented)
    assert not missing, f"pack settings absent from docs/PARAMETERS.md: {missing}"


def test_every_cli_command_is_documented():
    from winnow.cli import build_parser

    parser = build_parser()
    commands = set()
    for action in parser._actions:  # noqa: SLF001 - the public API exposes no listing
        if hasattr(action, "choices") and action.choices:
            commands |= set(action.choices)

    readme = README.read_text(encoding="utf-8")
    missing = sorted(c for c in commands if f"winnow {c}" not in readme)
    assert not missing, f"commands absent from the README: {missing}"


def test_readme_perturbation_count_matches_the_record():
    """The README claimed fourteen verified behaviours where the record listed eleven."""
    rows = len(re.findall(r"^\| \d+ \|", PERTURBATION.read_text(encoding="utf-8"), re.MULTILINE))
    readme = README.read_text(encoding="utf-8")
    words = {
        "Eleven": 11, "Twelve": 12, "Thirteen": 13, "Fourteen": 14,
        "Fifteen": 15, "Sixteen": 16, "Seventeen": 17, "Eighteen": 18,
        "Nineteen": 19, "Twenty": 20,
        "Twenty-one": 21, "Twenty-two": 22, "Twenty-three": 23, "Twenty-four": 24,
        "Twenty-five": 25, "Twenty-six": 26, "Twenty-seven": 27, "Twenty-eight": 28,
        "Twenty-nine": 29, "Thirty": 30,
    }
    claimed = [n for word, n in words.items() if f"{word} behaviours" in readme]
    assert claimed, "the README should state how many behaviours were perturbation-verified"
    assert claimed[0] == rows, (
        f"README claims {claimed[0]} perturbation-verified behaviours; "
        f"tests/PERTURBATION.md documents {rows}"
    )


def _tracked_markdown() -> list[str]:
    """Every tracked .md, discovered rather than listed.

    The hardcoded list of four missed five files, including a whole folder's worth added
    later. A link check that only covers the documents someone remembered to enumerate
    rots exactly where new writing happens.
    """
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(out) >= 8, f"expected the repo's markdown to be tracked, got {out}"
    return sorted(out)


@pytest.mark.parametrize("doc", _tracked_markdown())
def test_internal_links_resolve(doc):
    path = ROOT / doc
    text = path.read_text(encoding="utf-8")
    broken = []
    for link in re.findall(r"\]\((?!https?:)([^)#]+)", text):
        target = (path.parent / link).resolve()
        if not target.exists():
            broken.append(link)
    assert not broken, f"{doc} links to files that do not exist: {broken}"


def test_no_absolute_machine_paths_in_tracked_files():
    """A published repo must not carry anyone's filesystem layout.

    Only TRACKED files are examined: a user's own `winnow.json` legitimately holds absolute
    paths and is gitignored, so scanning the working tree would fail on correct usage.

    A single drive letter is also not enough to match on -- `https://` contains `s:/`.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()

    drive_path = re.compile(r"(?<![A-Za-z])[A-Za-z]:[/\\][A-Za-z0-9_./\\-]{4,}")
    home_path = re.compile(r"(?:/home/|/Users/)[A-Za-z0-9_.-]+/")

    offenders = []
    for rel in tracked:
        path = ROOT / rel
        if path.suffix not in (".py", ".md", ".json", ".toml", ".txt"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in (drive_path, home_path):
            for match in pattern.findall(text):
                offenders.append(f"{rel}: {match}")
    assert not offenders, f"absolute machine paths in tracked files: {offenders[:5]}"
