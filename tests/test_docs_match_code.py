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


_UNITS = [
    "", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _number_words(low: int, high: int) -> dict[str, int]:
    """Capitalised English number words in [low, high], as {word: value}.

    Generated rather than listed. The hardcoded map this replaces ran out twice, and when it
    did the test failed on its "no count found" branch -- reporting that the README states no
    count at all, when in fact it stated one the test could not spell.
    """
    words = {}
    for n in range(low, min(high, 99) + 1):
        if n < 20:
            word = _UNITS[n]
        else:
            tens, unit = divmod(n, 10)
            word = _TENS[tens] + (f"-{_UNITS[unit]}" if unit else "")
        words[word.capitalize()] = n
    return words


def test_readme_perturbation_count_matches_the_record():
    """The README claimed fourteen verified behaviours where the record listed eleven."""
    rows = len(re.findall(r"^\| \d+ \|", PERTURBATION.read_text(encoding="utf-8"), re.MULTILINE))
    readme = README.read_text(encoding="utf-8")
    # Generated, not listed. A hardcoded map ran out twice -- and when it did, the failure
    # was the "no count found" branch below, which describes the wrong problem entirely.
    claimed = [n for word, n in _number_words(1, 99).items() if f"{word} behaviours" in readme]
    assert claimed, (
        "the README should state how many behaviours were perturbation-verified, "
        "in words (e.g. 'Thirty-eight behaviours')"
    )
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


def _prose(text: str) -> str:
    """The document with code removed, because markdown makes no links inside code.

    A file whose subject is regular expressions is full of things shaped like links --
    tests/PERTURBATION.md contains the literal pattern `](` inside a code span -- and every
    link check below fired on them. Rewording the prose to please the checker is the wrong
    direction: the checker was reporting a link that markdown would never create.
    """
    text = re.sub(r"^```.*?^```", "", text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def test_prose_keeps_the_links_it_is_meant_to_check():
    """Guard the guard: a stripper that removed everything would pass every link test."""
    sample = "\n".join(
        [
            "See [the parameters](docs/PARAMETERS.md) and [an anchor](#exit-codes).",
            "The pattern `](` is code, and so is `[not a link](nowhere.md)`.",
            "```",
            "[fenced](also-nowhere.md)",
            "```",
            "",
        ]
    )
    prose = _prose(sample)

    assert "docs/PARAMETERS.md" in prose, "a real link was stripped along with the code"
    assert "#exit-codes" in prose, "a real anchor was stripped along with the code"
    assert "nowhere.md" not in prose, "an inline code span was scanned as prose"
    assert "also-nowhere.md" not in prose, "a fenced block was scanned as prose"


@pytest.mark.parametrize("doc", _tracked_markdown())
def test_internal_links_resolve(doc):
    path = ROOT / doc
    text = _prose(path.read_text(encoding="utf-8"))
    broken = []
    for link in re.findall(r"\]\((?!https?:)([^)#]+)", text):
        target = (path.parent / link).resolve()
        if not target.exists():
            broken.append(link)
    assert not broken, f"{doc} links to files that do not exist: {broken}"


def _heading_slugs(text: str) -> set[str]:
    """GitHub's anchor for a heading: lowercased, spaces to hyphens, punctuation dropped."""
    slugs = set()
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        slugs.add(slug)
    return slugs


@pytest.mark.parametrize("doc", _tracked_markdown())
def test_anchor_links_point_at_a_real_heading(doc):
    """The file-link check skips these: `[^)#]+` matches nothing after `](#`."""
    path = ROOT / doc
    raw = path.read_text(encoding="utf-8")
    slugs = _heading_slugs(raw)
    text = _prose(raw)

    broken = [a for a in re.findall(r"\]\(#([^)]+)\)", text) if a not in slugs]
    assert not broken, (
        f"{doc} links to anchors with no such heading: {broken}\n"
        f"  headings present: {sorted(slugs)}"
    )


@pytest.mark.parametrize("doc", _tracked_markdown())
def test_no_link_is_split_across_two_lines(doc):
    """`[text]` and `(target)` must touch, or markdown renders the brackets literally."""
    text = _prose((ROOT / doc).read_text(encoding="utf-8"))

    split = re.findall(r"\[[^\]\n]{1,80}\]\s*\n\s*\(", text)
    assert not split, (
        f"{doc} has a link whose target is on the next line, so it is not a link: {split}"
    )


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


def test_files_cited_in_the_source_exist():
    """A comment pointing at a document is a link, and rots like one.

    `config.py` cited a THIRD_PASS file under the experiments folder, which never existed
    -- the third-pass study is an addendum inside TWO_PASS.md. Someone checking where a
    default came from follows that to nothing. The markdown link check cannot see it,
    because it lives in a Python comment.

    (That path is spelled out here in prose rather than written literally: this file is
    scanned too, and a checker that trips on its own description of the bug is noise.)
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert len(tracked) > 20, f"expected a substantial .py listing, got {tracked}"

    cited = re.compile(r"\b((?:docs|experiments|tests|packs|scripts)/[A-Za-z0-9_./-]+\.(?:md|json|py|txt))")
    missing = []
    for rel in tracked:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for match in cited.findall(text):
            if not (ROOT / match).exists():
                missing.append(f"{rel}: {match}")
    assert not missing, f"source cites files that do not exist: {missing}"
