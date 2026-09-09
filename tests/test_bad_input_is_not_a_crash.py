"""Predictable input mistakes must be a sentence and an exit code, never a traceback.

`cli._run` says so in its own docstring, and the README publishes a table of exit codes so a
script can tell one failure from another. Four ordinary mistakes went straight past both:

    pack.json with no "name"        KeyError: 'name'
    winnow.json holding a JSON array   TypeError: 'int' object is not iterable
    text_num_ctx: 10                ValueError: num_ctx=10 is too small ...
    embed_backend: "cloud"          ValueError: unknown embedding backend 'cloud'

and a fifth is worse than a traceback: the handler for a corrupt corpus RE-READS the
configuration to name the corpus path. A second exception raised inside an exception handler
replaces the one-line database error with a chained traceback -- the handler defeating
itself.

`embed_backend: "cloud"` is the one with a documentation half. `Config.is_fully_local` and
`Config.egress_statement` both branch on it, so `winnow status` prints "NOT FULLY LOCAL ...
embed_backend is set to 'cloud'" and exits 0, describing the privacy consequences of a
backend that does not exist and cannot be built. A privacy statement about a phantom feature
is not a smaller problem than a crash.

Reported by an external review.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pytest

from winnow import cli
from winnow.config import EMBED_BACKENDS, Config, InvalidConfiguration
from winnow.embed import build_embedder
from winnow.packs import InvalidPack, load_pack

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"

TRACEBACK = "Traceback (most recent call last)"


def _config(tmp_path, **overrides) -> Path:
    body = {
        "pack": "ai_tooling",
        "corpus_path": str(tmp_path / "corpus.db"),
        "embed_backend": "hashing",
        "packs_root": str(PACKS_ROOT),
    }
    body.update(overrides)
    path = tmp_path / "winnow.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "a.md").write_text("throughput is bandwidth bound", encoding="utf-8")
    return folder


def _nameless_pack(tmp_path) -> Path:
    root = tmp_path / "packs"
    pack = root / "broken"
    pack.mkdir(parents=True)
    pack.joinpath("pack.json").write_text(
        json.dumps(
            {
                "version": "1",
                "description": "a manifest whose author forgot the one required field",
                "schema": {"claim": "the claim"},
                "extract_prompt": "extract.txt",
            }
        ),
        encoding="utf-8",
    )
    pack.joinpath("extract.txt").write_text("Find the claims in __TEXT__", encoding="utf-8")
    return root


# -- 1. a pack manifest missing its name -------------------------------------------------


def test_a_nameless_pack_is_an_invalid_pack(tmp_path):
    root = _nameless_pack(tmp_path)
    with pytest.raises(InvalidPack) as raised:
        load_pack(root / "broken")

    message = str(raised.value)
    assert "name" in message, f"say which field is missing: {message!r}"
    assert "pack.json" in message, f"name the file the author has to edit: {message!r}"


def test_a_manifest_that_is_not_an_object_is_an_invalid_pack(tmp_path):
    """The same mistake one level up: a list of packs written where one pack belongs."""
    pack = tmp_path / "packs" / "listy"
    pack.mkdir(parents=True)
    pack.joinpath("pack.json").write_text('["ai_tooling"]', encoding="utf-8")

    with pytest.raises(InvalidPack):
        load_pack(pack)


def test_the_cli_reports_a_nameless_pack_as_code_seven(tmp_path, capsys):
    root = _nameless_pack(tmp_path)
    config = _config(tmp_path, pack="broken", packs_root=str(root))

    code = cli.main(["--config", str(config), "packs"])
    said = "".join(capsys.readouterr())

    assert TRACEBACK not in said, f"a broken pack manifest crashed: {said}"
    assert code == 7, f"README documents 7 for an invalid pack, got {code}: {said!r}"


# -- 2. a configuration file of the wrong shape ------------------------------------------


@pytest.mark.parametrize("body", ['[1, 2, 3]', '"winnow.json"', "42", "null"])
def test_a_config_that_is_not_an_object_is_refused(tmp_path, body):
    path = tmp_path / "winnow.json"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(InvalidConfiguration) as raised:
        Config.load(path)

    assert "winnow.json" in str(raised.value), (
        f"name the file that has to be fixed: {str(raised.value)!r}"
    )


def test_the_cli_reports_a_misshapen_config_as_code_two(tmp_path, capsys):
    path = tmp_path / "winnow.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    code = cli.main(["--config", str(path), "status"])
    said = "".join(capsys.readouterr())

    assert TRACEBACK not in said, f"a config of the wrong shape crashed: {said}"
    assert code == 2, f"README documents 2 for bad input, got {code}: {said!r}"


# -- 3. a context window too small to extract from ---------------------------------------


def test_an_unusable_context_window_is_refused_before_any_work(tmp_path, capsys):
    config = _config(tmp_path, text_num_ctx=10)
    notes = _notes(tmp_path)

    code = cli.main(["--config", str(config), "index", str(notes)])
    said = "".join(capsys.readouterr())

    assert TRACEBACK not in said, f"an unusable text_num_ctx crashed: {said}"
    assert code == 2, f"README documents 2 for bad input, got {code}: {said!r}"
    assert "text_num_ctx" in said, (
        f"name the setting the user has to change, not just the number: {said!r}"
    )
    assert not (tmp_path / "corpus.db").exists(), (
        "the corpus was created before the configuration was found unusable"
    )


# -- 4. an embedding backend that does not exist -----------------------------------------


def test_an_unknown_embedding_backend_is_refused(tmp_path, capsys):
    config = _config(tmp_path, embed_backend="cloud")
    notes = _notes(tmp_path)

    code = cli.main(["--config", str(config), "index", str(notes)])
    said = "".join(capsys.readouterr())

    assert TRACEBACK not in said, f"an unknown embed_backend crashed: {said}"
    assert code == 2, f"README documents 2 for bad input, got {code}: {said!r}"
    for backend in EMBED_BACKENDS:
        assert backend in said, f"list the backends that do exist ({backend}): {said!r}"
    assert not (tmp_path / "corpus.db").exists(), (
        "the corpus was created before the configuration was found unusable"
    )


def test_status_does_not_describe_a_backend_that_does_not_exist(tmp_path, capsys):
    """`status` is the authority on privacy. It cannot describe a phantom backend."""
    config = _config(tmp_path, embed_backend="cloud")

    code = cli.main(["--config", str(config), "status"])
    said = "".join(capsys.readouterr())

    assert TRACEBACK not in said
    assert code != 0, (
        "status reported a configuration that cannot run as healthy: " + said
    )
    assert "cloud" in said and "embed_backend" in said, (
        f"say which setting is wrong: {said!r}"
    )


def test_a_directly_built_config_is_not_local_on_an_unknown_backend():
    """`Config.load` refuses these, but a Config can also be constructed in code."""
    config = Config(embed_backend="cloud")

    assert not config.is_fully_local, (
        "a backend Winnow cannot build was called fully local"
    )
    statement = config.egress_statement()
    assert "not a backend Winnow has" in statement, (
        "the privacy statement described the consequences of a phantom backend rather "
        f"than saying it does not exist: {statement!r}"
    )


def test_the_local_check_covers_every_unknown_backend_not_one_spelling():
    """It read `!= "cloud"`, which passed every other invented name as fully local."""
    for invented in ("openai", "s3", "", "OLLAMA"):
        assert not Config(embed_backend=invented).is_fully_local, (
            f"embed_backend={invented!r} is not a backend Winnow has, so where the text "
            "would go cannot be stated -- and an unstatable destination is not local"
        )


def test_every_named_backend_can_actually_be_built():
    """The list the error message quotes and the dispatch must not drift apart."""
    for backend in EMBED_BACKENDS:
        embedder = build_embedder(backend, "nomic-embed-text", "http://localhost:11434")
        assert embedder is not None


def test_an_unnamed_backend_is_a_configuration_error():
    with pytest.raises(InvalidConfiguration):
        build_embedder("cloud")


# -- 5. the error handler must not raise -------------------------------------------------


def _boom(_args):
    raise sqlite3.DatabaseError("file is not a database")


@pytest.mark.parametrize(
    "body, why",
    [
        ("{ not json", "malformed JSON"),
        ("[1, 2, 3]", "a JSON array"),
    ],
)
def test_the_database_handler_survives_an_unreadable_config(tmp_path, capsys, body, why):
    path = tmp_path / "winnow.json"
    path.write_text(body, encoding="utf-8")
    args = argparse.Namespace(config=str(path))

    code = cli._run(_boom, args)
    said = "".join(capsys.readouterr())

    assert code == 5, f"the database error is what happened, and 5 is its code ({why})"
    assert "file is not a database" in said, (
        f"the original failure must survive the handler ({why}): {said!r}"
    )


def test_the_database_handler_survives_a_config_that_is_a_directory(tmp_path, capsys):
    path = tmp_path / "winnow.json"
    path.mkdir()
    args = argparse.Namespace(config=str(path))

    code = cli._run(_boom, args)
    said = "".join(capsys.readouterr())

    assert code == 5
    assert "file is not a database" in said, f"the original failure was lost: {said!r}"


@pytest.mark.parametrize(
    "error",
    [
        IsADirectoryError(21, "Is a directory", "winnow.json"),
        NotADirectoryError(20, "Not a directory", "notes/x.md"),
        OSError(28, "No space left on device", "winnow.db"),
    ],
    ids=["a directory where a file belongs", "a file where a folder belongs", "a full disk"],
)
def test_an_operating_system_error_is_a_sentence_not_a_traceback(capsys, error):
    """`_run` catches FileNotFoundError and PermissionError. Those are not the only ones.

    Reading a directory raises PermissionError on Windows and IsADirectoryError elsewhere,
    so `winnow --config <a directory>` was a tidy exit code on the machine this was written
    on and a traceback on every other. A full disk was never handled anywhere.
    """
    def boom(_args):
        raise error

    code = cli._run(boom, argparse.Namespace(config=None))
    said = "".join(capsys.readouterr())

    assert "Traceback" not in said, said
    assert code == 2, f"an ordinary filesystem failure should be bad input, got {code}"
    assert error.strerror in said or str(error) in said, (
        f"say what the system said: {said!r}"
    )


def test_the_handler_still_names_the_corpus_when_it_can(tmp_path, capsys):
    """The guard: making the handler safe must not make it useless."""
    config = _config(tmp_path)
    args = argparse.Namespace(config=str(config))

    code = cli._run(_boom, args)
    said = "".join(capsys.readouterr())

    assert code == 5
    assert "corpus.db" in said, (
        f"the whole point of the handler is to name the file: {said!r}"
    )
