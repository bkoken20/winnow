"""Ctrl-C answered a long run with a traceback.

`index` on a real notes folder is minutes to hours. Stopping it is not an error condition and
not an unexpected exception — it is the documented way to change your mind, and the only way,
since the projection is shown before the run and the run has no other exit.

What it printed was a `KeyboardInterrupt` stack trace through `pipeline.py`, `extract.py` and
`llm.py`, ending in a `time.sleep` or a socket read. That reads as a crash, and it buries the
question the user actually has: **is the work I have already paid for still there?**

It is. `index_notes_folder` commits per file and `skip_known` filters out what is already
stored, so an interrupted index resumes where it stopped. Nothing said so, and a stack trace
is not where anyone looks for reassurance.

130 is the conventional code for a process ended by SIGINT (128 + 2), and it goes in the
README's table with the rest.

Reported by an external review.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


def _config(tmp_path) -> Path:
    path = tmp_path / "winnow.json"
    path.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
            }
        ),
        encoding="utf-8",
    )
    return path


def _interrupted(_args):
    raise KeyboardInterrupt


def test_an_interrupt_is_not_a_traceback(capsys):
    import argparse

    code = cli._run(_interrupted, argparse.Namespace(config=None))
    said = "".join(capsys.readouterr())

    assert "Traceback" not in said, said
    assert code == 130, f"128 + SIGINT is the convention, got {code}"


def test_it_says_the_work_so_far_is_kept(capsys):
    import argparse

    cli._run(_interrupted, argparse.Namespace(config=None))
    said = "".join(capsys.readouterr()).lower()

    assert "stopped" in said or "interrupted" in said, said

    # TWO things, not one. The first version accepted "kept" OR "already", and deleting the
    # sentence that says the work survives still passed -- because the sentence AFTER it
    # happens to contain "already". A user has two questions and the message owes both
    # answers: did I lose the work, and how do I carry on.
    survived = any(word in said for word in ("kept", "not lost", "still there"))
    continues = any(word in said for word in ("picks up", "resume", "re-run", "again"))
    assert survived, f"it does not say whether the work survived: {said!r}"
    assert continues, f"it does not say how to carry on: {said!r}"


def test_the_whole_command_returns_it(tmp_path, capsys, monkeypatch):
    """Through `main`, not just `_run` -- an uncaught interrupt escapes to the shell."""
    monkeypatch.setattr(cli, "cmd_status", _interrupted)

    code = cli.main(["status", "--config", str(_config(tmp_path))])
    said = "".join(capsys.readouterr())

    assert code == 130
    assert "Traceback" not in said


def test_an_interrupted_index_can_be_resumed(tmp_path, capsys, monkeypatch):
    """The claim the message makes has to be true, so run it.

    Index two files, interrupt during the second, then index again and watch it pick up
    only what is left.
    """
    from winnow.config import Config
    from winnow.pipeline import Pipeline

    notes = tmp_path / "notes"
    notes.mkdir()
    for i in range(4):
        (notes / f"{i}.md").write_text(
            f"subject {i} changes throughput by roughly {i + 3} percent", encoding="utf-8"
        )

    class LineClaimsLLM:
        def __init__(self):
            self.calls = 0

        def generate(self, model, prompt, *, num_ctx, as_json=False):
            self.calls += 1
            if self.calls > 3:
                raise KeyboardInterrupt
            body = prompt.split("SOURCE MATERIAL:")[-1].strip()
            return json.dumps(
                {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
            )

    corpus = tmp_path / "winnow.db"

    def build(config):
        pipeline = Pipeline.build(config)
        pipeline.extractor.llm = LineClaimsLLM()
        return pipeline

    config = Config(
        pack="ai_tooling",
        corpus_path=str(corpus),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        index_extra_passes=[],
    )

    first = build(config)
    try:
        with pytest.raises(KeyboardInterrupt):
            first.index_notes_folder(notes, accept_minutes=600)
    finally:
        first.close()
    capsys.readouterr()

    from winnow.store import Store

    store = Store.open_readonly(str(corpus))
    try:
        kept = store.count_claims("ai_tooling")
        done = len(store.source_paths("ai_tooling"))
    finally:
        store.close()

    assert kept > 0, "an interrupted run threw away everything it had already paid for"
    assert done < 4, "the fixture did not actually interrupt anything"

    # And the rest is picked up rather than redone.
    second = Pipeline.build(config)
    second.extractor.llm = LineClaimsLLM()
    try:
        again = second.index_notes_folder(notes, accept_minutes=600)
    finally:
        second.close()
    capsys.readouterr()

    assert again["files"] == 4 - done, (
        f"{done} files were already stored, so {4 - done} were left; it did {again['files']}"
    )


def test_the_exit_code_is_documented():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8"
    )

    assert "`130`" in readme, "a code the tool can return belongs in the table"
    assert "Ctrl" in readme or "interrupt" in readme.lower()
