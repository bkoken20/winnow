"""Predictable mistakes must produce a sentence, not a stack trace.

`winnow index <mistyped-path>` -- the single most likely thing a user will get wrong --
printed a Python traceback. A tool that answers an ordinary mistake that way reads as broken
rather than as strict, and buries the one line that would have helped.

What is deliberately NOT covered here: genuinely unexpected exceptions still propagate in
full. A crash nobody planned for should be loud and complete, not flattened into a tidy
message that hides where it came from.
"""

import json
from pathlib import Path

import pytest

from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "winnow.json"
    path.write_text(
        json.dumps(
            {
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
            }
        ),
        encoding="utf-8",
    )
    return path


def run(config_file, *argv) -> int:
    return cli.main(["--config", str(config_file), *argv])


def test_indexing_a_missing_folder_says_so(config_file, tmp_path, capsys):
    code = run(config_file, "index", str(tmp_path / "does-not-exist"))
    err = capsys.readouterr().err
    assert code == 2
    assert "no such folder" in err
    assert "Traceback" not in err


def test_indexing_a_file_instead_of_a_folder_says_so(config_file, tmp_path, capsys):
    a_file = tmp_path / "notes.md"
    a_file.write_text("hello", encoding="utf-8")
    code = run(config_file, "index", str(a_file))
    err = capsys.readouterr().err
    assert code == 2
    assert "not a folder" in err
    assert "Traceback" not in err


def test_ingesting_a_missing_path_says_so(config_file, tmp_path, capsys):
    code = run(config_file, "ingest", str(tmp_path / "nothing"))
    err = capsys.readouterr().err
    assert code == 2
    assert "no such file or folder" in err
    assert "Traceback" not in err


def test_a_malformed_config_names_the_file(config_file, tmp_path, capsys):
    bad = tmp_path / "broken.json"
    bad.write_text("{oops", encoding="utf-8")
    code = cli.main(["--config", str(bad), "status"])
    err = capsys.readouterr().err
    assert code == 2
    assert "malformed JSON" in err
    assert "broken.json" in err, "the message must say WHICH file is malformed"


def test_a_malformed_pack_names_the_file(tmp_path, capsys):
    packs = tmp_path / "packs" / "bad"
    packs.mkdir(parents=True)
    (packs / "pack.json").write_text("{not json", encoding="utf-8")
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({"pack": "bad", "packs_root": str(tmp_path / "packs")}), encoding="utf-8"
    )

    code = cli.main(["--config", str(config), "packs"])
    err = capsys.readouterr().err
    assert code == 2
    assert "pack.json" in err, "the message must name the offending manifest"


def test_a_missing_pack_lists_what_is_available(config_file, tmp_path, capsys):
    config = tmp_path / "w2.json"
    config.write_text(
        json.dumps({"pack": "nonexistent", "packs_root": str(PACKS_ROOT)}), encoding="utf-8"
    )
    code = cli.main(["--config", str(config), "index", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "ai_tooling" in err, "an unknown pack should say which packs do exist"


def test_unexpected_errors_are_not_swallowed(config_file, monkeypatch):
    """The handler must not become a blanket `except Exception`.

    Catching everything would turn a real bug into a tidy message and hide the traceback
    that locates it.
    """

    def boom(args):
        raise ZeroDivisionError("a genuine bug")

    monkeypatch.setattr(cli, "cmd_status", boom)
    with pytest.raises(ZeroDivisionError):
        cli.main(["--config", str(config_file), "status"])
