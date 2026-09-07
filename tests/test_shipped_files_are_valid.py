"""Every shipped Python file must compile and pass a static check.

Three experiment scripts once shipped with a syntax error -- a literal newline inside an
f-string -- and the whole suite stayed green, because nothing imported them. A file nobody
runs in CI is a file nobody knows is broken until a stranger clones the repository and it
fails on line one. After that was fixed, one of the same scripts still referenced a
module-level name that existed only in its siblings: it parsed cleanly, then died with a
NameError on the first line of real work.

Compiling is a deliberately low bar -- these scripts need a model server, a corpus and tens
of minutes to run properly, which cannot go in a test suite. Pyflakes raises that bar to
"every name resolves" for roughly no cost.

A note on how this test was arrived at: the first version hand-rolled the undefined-name
analysis with `ast`, produced sixteen false positives (it did not know about `__file__`),
and missed a real undefined name that pyflakes found immediately. Hand-rolled static
analysis is a bad trade; use the tool that exists.
"""

import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _tracked_python_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return sorted(out.stdout.split())


TRACKED = _tracked_python_files()


def test_the_repository_actually_ships_python_files():
    """Guard the guard: if the listing breaks, every test below passes vacuously."""
    assert len(TRACKED) > 20, f"expected a substantial tracked .py listing, got {TRACKED}"


@pytest.mark.parametrize("relpath", TRACKED)
def test_shipped_file_compiles(relpath):
    path = ROOT / relpath
    cfile = path.with_suffix(path.suffix + ".testc")
    try:
        py_compile.compile(str(path), doraise=True, cfile=str(cfile))
    except py_compile.PyCompileError as exc:
        pytest.fail(f"{relpath} does not compile:\n{exc}")
    finally:
        cfile.unlink(missing_ok=True)


def _pyflakes_available() -> bool:
    return (
        subprocess.run(
            [sys.executable, "-m", "pyflakes", "--version"], capture_output=True
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _pyflakes_available(), reason="pyflakes not installed")
def test_no_undefined_names_or_unused_imports():
    """Names must resolve, everywhere -- including in files no test imports."""
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", *TRACKED],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    findings = [line for line in result.stdout.splitlines() if line.strip()]
    assert not findings, "pyflakes findings:\n  " + "\n  ".join(findings)
