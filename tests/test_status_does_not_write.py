"""`winnow status` wrote its schema into whatever database it was pointed at.

`status` was fixed once already: it no longer CREATES a corpus that is not there. But when
the file exists it still builds a `Store`, and `Store.__init__` runs `executescript(SCHEMA)`
followed by a `commit()`. So the diagnostic writes.

Measured, sha256 and table list before and after a single `winnow status`:

    zero-byte file        0 B, no tables      ->  53,248 B, 4 tables
    older schema     12,288 B, ['claims']     ->  36,864 B, 4 tables, then exit 5
    a budget         8,192 B, ['budget']      ->  57,344 B, ['budget', 'claims', 'meta',
                                                             'sources', 'verdicts']

The third is the one that matters. Mistype `corpus_path` onto a SQLite file that belongs to
something else and Winnow silently adds four tables to it and exits 0. The second is nearly
as bad: the file is modified and THEN the command reports failure.

A diagnostic must not be able to do this, and "remember to open it read-only" is not a
mechanism. SQLite has one: a `file:...?mode=ro` URI makes every write raise
`sqlite3.OperationalError: attempt to write a readonly database`, enforced by the database
rather than promised by the caller.

Reported by an external review.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from winnow import cli
from winnow.store import Store

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


def _config(tmp_path, corpus: Path) -> Path:
    path = tmp_path / "winnow.json"
    path.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(corpus),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
            }
        ),
        encoding="utf-8",
    )
    return path


def _fingerprint(path: Path) -> tuple:
    data = path.read_bytes()
    return (len(data), hashlib.sha256(data).hexdigest())


def _tables(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return sorted(
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        )
    finally:
        conn.close()


def test_status_does_not_touch_someone_elses_database(tmp_path, capsys):
    """The worst case: a mistyped `corpus_path` pointing at a file that is not ours."""
    corpus = tmp_path / "household.db"
    conn = sqlite3.connect(corpus)
    conn.execute("CREATE TABLE budget (item TEXT, amount REAL)")
    conn.execute("INSERT INTO budget VALUES ('rent', 900.0)")
    conn.commit()
    conn.close()

    before = _fingerprint(corpus)
    cli.main(["status", "--config", str(_config(tmp_path, corpus))])
    capsys.readouterr()

    assert _fingerprint(corpus) == before, (
        f"a diagnostic modified a database that is not Winnow's: "
        f"{_tables(corpus)}"
    )
    assert _tables(corpus) == ["budget"], "Winnow added its own tables to it"


def test_status_does_not_initialise_an_empty_file(tmp_path, capsys):
    corpus = tmp_path / "winnow.db"
    corpus.write_bytes(b"")

    cli.main(["status", "--config", str(_config(tmp_path, corpus))])
    capsys.readouterr()

    assert corpus.stat().st_size == 0, "an empty file was turned into a corpus by looking"


def test_status_does_not_migrate_an_older_schema(tmp_path, capsys):
    """It added the missing tables and THEN reported the corpus unreadable."""
    corpus = tmp_path / "winnow.db"
    conn = sqlite3.connect(corpus)
    conn.execute("CREATE TABLE claims (id TEXT PRIMARY KEY, text TEXT)")
    conn.commit()
    conn.close()

    before = _fingerprint(corpus)
    code = cli.main(["status", "--config", str(_config(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert _fingerprint(corpus) == before, "the file was modified on the way to failing"
    assert code == 5, f"an unreadable corpus is 5: {said!r}"


def test_status_still_reports_a_real_corpus(tmp_path, capsys):
    """The mirror: a read-only diagnostic that cannot read is not a diagnostic."""
    corpus = tmp_path / "winnow.db"
    Store(str(corpus)).close()

    before = _fingerprint(corpus)
    code = cli.main(["status", "--config", str(_config(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert code == 0, said
    assert "0 claims" in said, f"it must still say what is in there: {said!r}"
    assert _fingerprint(corpus) == before


def test_status_on_a_missing_corpus_is_unchanged(tmp_path, capsys):
    """The earlier fix stays fixed: nothing is created, and it says so."""
    corpus = tmp_path / "nested" / "winnow.db"

    code = cli.main(["status", "--config", str(_config(tmp_path, corpus))])
    said = "".join(capsys.readouterr())

    assert code == 0
    assert not corpus.exists()
    assert not corpus.parent.exists()
    assert "no corpus" in said.lower()


# -- the mechanism -----------------------------------------------------------------------


def test_a_read_only_store_refuses_writes(tmp_path):
    """Enforced by SQLite, not by the caller remembering which methods are safe."""
    corpus = tmp_path / "winnow.db"
    Store(str(corpus)).close()

    store = Store.open_readonly(str(corpus))
    try:
        assert store.count_claims("ai_tooling") == 0
        with pytest.raises(sqlite3.OperationalError) as raised:
            store.conn.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
        assert "readonly" in str(raised.value).lower()
    finally:
        store.close()


def test_a_read_only_store_does_not_create_anything(tmp_path):
    corpus = tmp_path / "absent.db"

    with pytest.raises(sqlite3.OperationalError):
        Store.open_readonly(str(corpus))

    assert not corpus.exists(), "opening for reading created the file"


@pytest.mark.parametrize(
    "folder",
    ["with#hash", "with space", "plain", "with'quote", "with&amp"],
    ids=["hash", "space", "plain", "quote", "ampersand"],
)
def test_a_corpus_path_is_a_filename_not_a_uri(tmp_path, folder):
    """Found by walking the read-only constructor, not by running it.

    The URI was built by concatenation: `f"file:{path}?mode=ro"`. A `#` in the path starts a
    fragment, so the filename was truncated and SQLite opened something else -- a corpus
    sitting right there reported as `no such table: claims`. A `?`, legal on Linux and
    macOS, starts the query string and could drop the `mode=ro` this constructor exists for.
    """
    home = tmp_path / folder
    home.mkdir()
    corpus = home / "winnow.db"
    Store(str(corpus)).close()

    store = Store.open_readonly(str(corpus))
    try:
        assert store.count_claims("ai_tooling") == 0
    finally:
        store.close()


def test_a_relative_corpus_path_opens_read_only(tmp_path, monkeypatch):
    """`corpus_path` defaults to the bare name `winnow.db`, and a URI needs an absolute."""
    monkeypatch.chdir(tmp_path)
    Store("winnow.db").close()

    store = Store.open_readonly("winnow.db")
    try:
        assert store.count_claims("ai_tooling") == 0
    finally:
        store.close()


def test_a_writable_store_is_still_writable(tmp_path):
    """The guard: the read-only door must not lock the normal one."""
    corpus = tmp_path / "winnow.db"
    store = Store(str(corpus))
    try:
        store.conn.execute("INSERT INTO meta (key, value) VALUES ('probe', '1')")
        store.conn.commit()
    finally:
        store.close()

    assert "meta" in _tables(corpus)
