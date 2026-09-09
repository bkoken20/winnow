"""What `git archive HEAD` contains is what a stranger gets. Nothing else is.

The review found the working directory holding a 2.1 MB `winnow.db` with 383 claims, 167
sources and absolute local paths; a `winnow.json` with local paths; fetched captions under
`winnow-cache/`; a stale `build/` whose copies of the source differ from the tree; a
`winnow.egg-info` carrying an older README; and a `.pytest_cache`. Every one of them is
gitignored and none is tracked — the repository is clean.

Which is exactly why this needs a test rather than a note. The failure mode is not a bad
commit; it is **publishing by copying the folder**, at which point all of it ships. So the
check is on the thing that would actually be published.

Reported by an external review: "Publish from a clean Git checkout or `git archive`, not by
copying the whole folder."
"""
from __future__ import annotations

import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Substrings that must never appear in a published archive, and why.
NEVER_SHIP = {
    ".db": "a corpus holds claim text and absolute local paths",
    "winnow.json": "a local configuration holds absolute local paths",
    "winnow-cache/": "fetched captions are someone else's copyrighted material",
    "build/": "stale copies of the source that differ from the tree",
    ".egg-info": "generated metadata, often from an older README",
    ".pytest_cache": "one machine's test run",
    "__pycache__": "compiled bytecode",
}

# Files without which the archive is not this project.
MUST_SHIP = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "winnow/cli.py",
    "winnow/pipeline.py",
    "packs/ai_tooling/pack.json",
    "tests/PERTURBATION.md",
]


def _archive_names() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "winnow.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
            cwd=ROOT, check=True, capture_output=True,
        )
        with tarfile.open(archive) as tar:
            return tar.getnames()


def _offenders(names) -> list[str]:
    return [
        f"{name} ({why})"
        for name in names
        for fragment, why in NEVER_SHIP.items()
        if fragment in name
    ]


def test_the_detector_finds_what_it_is_looking_for():
    """Guard the guard: a check that matches nothing passes on any archive at all."""
    pretend = ["README.md", "winnow.db", "build/lib/winnow/cli.py", "winnow/__pycache__/x.pyc"]
    found = _offenders(pretend)

    assert len(found) == 3, f"the detector missed a local artifact: {found}"
    assert all("README.md" not in f for f in found), "a real file was reported as an artifact"


def test_no_local_artifact_would_be_published():
    offenders = _offenders(_archive_names())
    assert not offenders, (
        "git archive would publish local artifacts, so a release built from it leaks them: "
        f"{offenders[:10]}"
    )


def test_the_archive_is_actually_the_project():
    """The mirror: an archive can be clean by being empty."""
    names = set(_archive_names())
    missing = [f for f in MUST_SHIP if f not in names]

    assert not missing, f"git archive HEAD does not contain {missing}"


def test_the_release_procedure_is_written_down():
    """A rule nobody can read is a rule that holds until the day someone else releases."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "git archive" in readme, (
        "the README should say how to publish: from a clean checkout or `git archive`, "
        "never by copying the working folder"
    )
