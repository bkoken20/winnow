"""`winnow status` must observe, not alter, and must not report success over a failure.

Two faults in one command.

CREATION. `status` builds a `Store`, and `Store.__init__` makes missing parent directories
and opens SQLite -- which CREATES the database file. So running the diagnostic on a fresh
machine leaves a `winnow.db` behind that the user never asked for, and the folders above it.
A command whose job is to tell you the state should not be one of the things that changes it.

EXIT CODE. Yesterday's review said status reports a database failure and exits zero. I fixed
the embedding-mismatch branch to return 6 and left the broad handler returning 0, so a
corrupt or unreadable corpus still passes `winnow status && ...`. That is the same finding,
half-fixed -- and the README documents code 5 for a corpus database error.

Both reported by external reviews.
"""
from __future__ import annotations

import json
from pathlib import Path


from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


def _config(tmp_path, corpus: Path, **overrides) -> Path:
    body = {
        "pack": "ai_tooling",
        "corpus_path": str(corpus),
        "embed_backend": "hashing",
        "packs_root": str(PACKS_ROOT),
    }
    body.update(overrides)
    path = tmp_path / "winnow.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_status_does_not_create_the_corpus(tmp_path, capsys):
    corpus = tmp_path / "winnow.db"
    code = cli.main(["--config", str(_config(tmp_path, corpus)), "status"])
    said = "".join(capsys.readouterr())

    assert not corpus.exists(), (
        "a diagnostic command created the database it was asked to report on"
    )
    assert code == 0
    assert "no corpus" in said.lower() or "not created" in said.lower(), (
        f"say plainly that there is nothing there yet: {said!r}"
    )


def test_status_does_not_create_parent_directories(tmp_path, capsys):
    corpus = tmp_path / "nested" / "deeper" / "winnow.db"
    cli.main(["--config", str(_config(tmp_path, corpus)), "status"])
    capsys.readouterr()

    assert not (tmp_path / "nested").exists(), (
        "status made directories on a machine that had none"
    )


def test_an_unreadable_corpus_is_reported_and_fails(tmp_path, capsys):
    """A health check that passes over a damaged database is worse than none."""
    corpus = tmp_path / "winnow.db"
    corpus.write_text("this is not a database", encoding="utf-8")

    code = cli.main(["--config", str(_config(tmp_path, corpus)), "status"])
    said = "".join(capsys.readouterr()).lower()

    assert "unreadable" in said or "not a database" in said
    assert code == 5, (
        f"the README documents 5 for a corpus database error; status returned {code}"
    )


def test_a_healthy_corpus_still_reports_success(tmp_path, capsys):
    """The guard: ordinary use must not start failing."""
    from winnow.models import Claim, Source
    from winnow.store import Store
    from winnow.embed import HashingEmbedder

    corpus = tmp_path / "winnow.db"
    store = Store(corpus)
    embedder = HashingEmbedder()
    store.add_source(Source(id="s", pack="ai_tooling", kind="note", path="/x"))
    store.add_claim(
        Claim(id="c1", pack="ai_tooling", source_id="s", text="a claim"),
        embedder.embed("a claim"), embedder.name,
    )
    store.close()

    # embed_model must match what the claim was stored under, or status correctly reports a
    # mismatch and this "healthy" fixture is not healthy at all.
    config = _config(tmp_path, corpus, embed_model=embedder.name)
    code = cli.main(["--config", str(config), "status"])
    said = "".join(capsys.readouterr())

    assert code == 0, said
    assert "1 claims" in said


def test_a_mismatched_embedding_model_still_returns_six(tmp_path, capsys):
    """The guard for yesterday's fix, which this one must not undo."""
    from winnow.models import Claim, Source
    from winnow.store import Store
    from winnow.embed import HashingEmbedder

    corpus = tmp_path / "winnow.db"
    store = Store(corpus)
    embedder = HashingEmbedder()
    store.add_source(Source(id="s", pack="ai_tooling", kind="note", path="/x"))
    store.add_claim(
        Claim(id="c1", pack="ai_tooling", source_id="s", text="a claim"),
        embedder.embed("a claim"), embedder.name,
    )
    store.close()

    config = _config(tmp_path, corpus, embed_backend="ollama", embed_model="nomic-embed-text")
    code = cli.main(["--config", str(config), "status"])
    said = "".join(capsys.readouterr())

    assert "UNUSABLE" in said
    assert code == 6


def test_status_leaves_no_trace_on_a_directory_it_cannot_use(tmp_path, capsys):
    """A corpus path pointing at a directory is a configuration mistake, not a crash."""
    corpus = tmp_path / "a_directory"
    corpus.mkdir()

    code = cli.main(["--config", str(_config(tmp_path, corpus)), "status"])
    said = "".join(capsys.readouterr()).lower()

    assert code in (0, 5), f"exit {code}: {said!r}"
    assert "traceback" not in said
