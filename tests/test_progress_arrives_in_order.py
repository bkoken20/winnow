"""A run's account of itself arrived out of order the moment it was redirected to a file.

Captured from a real ingest, `python -m winnow.cli ingest <url> > log.txt 2>&1`:

    transcript: winnow-cache\\youtu-be-IH8XmxiwliQ-7ba82fc9\\video.en-orig.vtt
    pass 1 of 3: 2000-character chunks, 11 model calls
    pass 2 of 3: 1000-character chunks, 22 model calls
    pass 3 of 3: 4000-character chunks, 6 model calls
    using cached material in winnow-cache\\youtu-be-IH8XmxiwliQ-7ba82fc9
    72 claims after de-duplication in 4.8 minutes

`using cached material` is printed BEFORE the pipeline is built, four lines before the first
pass can possibly start. It appears fifth. The announcements go to stderr, which Python
line-buffers; that one goes to stdout, which is block-buffered as soon as it is not a
terminal. So it sat in a buffer for five minutes while the run it was describing went past
it, and the log says the cache was consulted after the work was done.

`winnow.acquire.announce_flushed` already exists and its docstring already diagnoses exactly
this, for the yt-dlp line one layer down:

    A bare `print` is block-buffered when stdout is a pipe, so piped into a log, `| tee` or
    CI the announcement sat in the buffer while yt-dlp ran and failed, and the user read the
    error ABOVE the command that caused it. Observed against a real 429 from YouTube.

The reasoning was applied to the line that motivated it and to nothing else.

Checked structurally rather than by running a redirected subprocess, because reproducing the
defect needs real block buffering AND a real model behind it -- neither of which exists in
CI. What is checked is the property that makes the ordering right: a status line printed
before the work starts must leave Python's buffers when it is written.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

CLI = pathlib.Path(__file__).resolve().parent.parent / "winnow" / "cli.py"
SOURCE = CLI.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in winnow/cli.py")


def _prints_in(func: ast.FunctionDef) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _reaches_the_user_immediately(call: ast.Call) -> bool:
    """Either flushed explicitly, or on stderr, which Python line-buffers regardless."""
    flush = _keyword(call, "flush")
    if isinstance(flush, ast.Constant) and flush.value is True:
        return True
    stream = _keyword(call, "file")
    return isinstance(stream, ast.Attribute) and stream.attr == "stderr"


def _work_starts_at(func: ast.FunctionDef) -> int:
    """The line where the long operation begins -- everything before it is a status line."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "build"
        ):
            return node.lineno
    raise AssertionError("no Pipeline.build in cmd_ingest; this test needs rewriting")


def test_every_status_line_before_the_work_reaches_the_user_when_it_is_written():
    ingest = _function("cmd_ingest")
    starts = _work_starts_at(ingest)

    stranded = [
        (call.lineno, ast.get_source_segment(SOURCE, call.args[0]) if call.args else "")
        for call in _prints_in(ingest)
        if call.lineno < starts and not _reaches_the_user_immediately(call)
    ]

    assert not stranded, (
        "these lines are printed before the work starts but can sit in a block buffer "
        f"until the run ends, so a redirected log shows them after it: {stranded}"
    )


@pytest.mark.parametrize("name", ["cmd_ingest", "cmd_index", "cmd_rejudge"])
def test_a_command_that_reports_progress_does_not_split_it_across_two_streams(name):
    """One stream for the narrative, or its order is at the mercy of two buffers.

    Ordering between stdout and stderr is only guaranteed while both reach the file as they
    are written. Mixing an unflushed stdout line into a stderr narrative is what produced
    the log above, and no amount of care at one call site fixes the next one.
    """
    func = _function(name)
    # Only what is printed BEFORE the work. A summary line printed after it is a result,
    # not progress: nothing follows it that could overtake it, and the interpreter flushes
    # on exit. Requiring those to flush would be ceremony with no failure behind it.
    starts = _work_starts_at(func)

    unflushed_stdout = [
        call.lineno
        for call in _prints_in(func)
        if _keyword(call, "file") is None
        and not _reaches_the_user_immediately(call)
        and call.lineno < starts
    ]

    assert not unflushed_stdout, (
        f"{name} prints to stdout without flushing at lines {unflushed_stdout}, while its "
        "other progress lines go to stderr; the two orders are decided by different buffers"
    )


@pytest.mark.parametrize(
    "snippet, immediate",
    [
        ('print("x")', False),
        ('print("x", flush=True)', True),
        ('print("x", flush=False)', False),
        ('print("x", file=sys.stderr)', True),
        ('print("x", file=sys.stdout)', False),
        ('print("x", file=sys.stdout, flush=True)', True),
    ],
)
def test_the_check_can_tell_the_two_apart(snippet, immediate):
    """The helper above decides every result in this file, so it needs its own evidence.

    Without this, replacing its body with `return True` was caught only by pyflakes
    objecting to the now-unused variable -- a kill for the wrong reason, which is
    indistinguishable from no kill at all once the dead code is tidied away.
    """
    call = ast.parse(snippet).body[0].value
    assert _reaches_the_user_immediately(call) is immediate
