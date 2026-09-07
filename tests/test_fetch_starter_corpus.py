"""The starter-corpus fetcher: the one script a new user runs before anything else.

It is checked for syntax and undefined names by test_shipped_files_are_valid, and nothing
else. It is also the first thing that touches the network on a stranger's machine and the
thing that decides how long their first run takes, so its bounds are worth pinning.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "fetch_starter_corpus.py"

sys.path.insert(0, str(ROOT / "scripts"))

from fetch_starter_corpus import copy_markdown, main  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path):
    """A source tree with stubs and substantial pages, as a docs repo actually has."""
    src = tmp_path / "repo"
    (src / "docs").mkdir(parents=True)
    for i in range(4):
        (src / "docs" / f"stub{i}.md").write_text("# title\n", encoding="utf-8")
    for i in range(6):
        (src / "docs" / f"real{i}.md").write_text("x" * 3000, encoding="utf-8")
    return src


def test_a_limit_of_zero_copies_nothing(fake_repo, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    assert copy_markdown(fake_repo, ["docs/"], dest, "r", limit=0) == 0
    assert list(dest.iterdir()) == []


def test_the_command_line_honours_a_limit_of_zero(fake_repo, tmp_path, monkeypatch, capsys):
    """`--limit 0` must mean none, not all.

    main() tested the limit for truthiness -- `if args.limit and ...` -- so 0 was read as
    "no limit given" and the full corpus was fetched: the 3.5-hour job, from a flag asking
    for nothing. copy_markdown itself gets this right (`limit is not None`), which is what
    makes the inconsistency easy to miss.
    """
    import fetch_starter_corpus as fsc

    monkeypatch.setattr(fsc, "load_sources", lambda pack: [
        {"name": "fake", "url": "https://example.invalid/repo", "paths": ["docs/"],
         "license": "MIT", "why": "a fake source"}
    ])
    monkeypatch.setattr(fsc, "have_git", lambda: True)

    def fake_clone(cmd, **kwargs):
        # git clone <url> <tmp> -- populate the destination as a real clone would
        target = Path(cmd[-1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "docs").mkdir(exist_ok=True)
        for i in range(6):
            (target / "docs" / f"real{i}.md").write_text("x" * 3000, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(fsc.subprocess, "run", fake_clone)

    dest = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "fetch_starter_corpus.py", "--pack", "ai_tooling", "--dest", str(dest), "--limit", "0"
    ])
    main()
    capsys.readouterr()

    written = list(dest.glob("*.md")) if dest.exists() else []
    assert written == [], f"--limit 0 fetched {len(written)} files"


def test_a_limit_prefers_substantial_pages_over_stubs(fake_repo, tmp_path):
    """Documented behaviour: taking the smallest files produced a corpus of zero claims."""
    dest = tmp_path / "out"
    dest.mkdir()
    copy_markdown(fake_repo, ["docs/"], dest, "r", limit=3)
    names = sorted(p.name for p in dest.iterdir())
    assert all("stub" not in n for n in names), f"picked stubs: {names}"


def test_existing_files_are_left_alone(fake_repo, tmp_path):
    """The docstring promises re-running is safe."""
    dest = tmp_path / "out"
    dest.mkdir()
    copy_markdown(fake_repo, ["docs/"], dest, "r")
    before = {p.name: p.read_text(encoding="utf-8") for p in dest.iterdir()}
    victim = next(iter(before))
    (dest / victim).write_text("edited by the user", encoding="utf-8")

    copy_markdown(fake_repo, ["docs/"], dest, "r")
    assert (dest / victim).read_text(encoding="utf-8") == "edited by the user"


def test_the_help_text_describes_what_the_code_does():
    """`--help` said "smallest files first", which is the behaviour that was replaced.

    Sorting by size alone picked stubs and produced a corpus of zero claims; the code now
    prefers substantial pages, and docs/DOMAIN_PACKS.md says so. The script's own help did
    not, and `--help` is where someone actually looks.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=True
    )
    helptext = " ".join(result.stdout.split())
    assert "smallest files first" not in helptext.lower(), (
        "the help promises the superseded behaviour: sorting by size alone picked stubs"
    )
    assert "substantial" in helptext.lower() or "stub" in helptext.lower()
