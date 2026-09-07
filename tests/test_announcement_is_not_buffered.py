"""The fetch announcement must actually reach the user before the fetch runs.

The README and docs/ACQUISITION.md both promise it: "the exact command is printed before it
runs", so nothing reaches the network without appearing on screen first. That is a privacy
guarantee, not a progress message.

It was printed with a bare `print`, which Python BLOCK-BUFFERS when stdout is a pipe. Piped
into anything -- a log file, `| tee`, CI -- the announcement sat in a buffer while the
subprocess ran and failed, so the user saw yt-dlp's error first and the command afterwards.
Observed for real: a 429 from YouTube printed above the `running:` line that was supposed to
precede it.

Testing this needs a real pipe, so this test runs a child process rather than using capsys:
capsys captures stdout and stderr separately, which discards the interleaving that IS the
defect.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = textwrap.dedent(
    """
    import sys, subprocess
    sys.path.insert(0, {root!r})

    from winnow import acquire

    # Stand in for yt-dlp: writes to stderr, exactly as the real one does on failure.
    def fake_run(cmd, **kwargs):
        print("YTDLP-STDERR-MARKER", file=sys.stderr, flush=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    acquire.subprocess.run = fake_run
    acquire.yt_dlp_command = lambda: ["yt-dlp"]

    dest = {dest!r}
    try:
        acquire.fetch("https://example.invalid/v", dest)
    except acquire.AcquisitionFailed:
        pass          # no captions written; the announcement is what matters here
    """
)


def test_the_command_is_flushed_before_the_fetch_runs(tmp_path):
    child = CHILD.format(root=str(ROOT), dest=str(tmp_path / "out"))
    result = subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True,      # a PIPE, which is what triggers block buffering
        text=True,
        cwd=str(ROOT),
    )
    merged = result.stdout + result.stderr

    assert "running: yt-dlp" in merged, f"the command was never announced. Got: {merged!r}"

    # Re-run with the two streams merged into ONE pipe, so ordering is observable.
    with subprocess.Popen(
        [sys.executable, "-c", child],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(ROOT),
    ) as proc:
        combined, _ = proc.communicate(timeout=60)

    announce_at = combined.find("running: yt-dlp")
    subprocess_at = combined.find("YTDLP-STDERR-MARKER")

    assert announce_at != -1 and subprocess_at != -1, f"missing markers in: {combined!r}"
    assert announce_at < subprocess_at, (
        "the command appeared AFTER the process it describes had already written output. "
        "Piped into a log or CI, the promise that nothing reaches the network without "
        f"appearing first does not hold. Output was:\n{combined}"
    )
