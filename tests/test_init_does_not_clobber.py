"""`winnow init` must not destroy a config the user already owns.

It used to load the existing file and write it back. Known settings survived that round
trip; anything else did not. A config carrying

    "_comment": "tuned for my dense reference corpus - do not change"

lost the note by running a command whose name reads as harmless. Rewriting a file the user
already wrote is not what "init" means.
"""

import json
from pathlib import Path

from winnow import cli
from winnow.config import Config


def existing_config(tmp_path, **extra) -> Path:
    path = tmp_path / "winnow.json"
    payload = {
        "text_num_ctx": 8192,
        "chunk_chars": 500,
        "_comment": "tuned for my dense reference corpus - do not change",
    }
    payload.update(extra)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_init_refuses_to_overwrite_an_existing_config(tmp_path, capsys):
    path = existing_config(tmp_path)
    before = path.read_text(encoding="utf-8")

    code = cli.main(["--config", str(path), "init"])

    assert code == 2
    assert path.read_text(encoding="utf-8") == before, "the file must be untouched, byte for byte"
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "--force" in err, "the message must say how to proceed deliberately"


def test_the_users_own_keys_survive(tmp_path):
    """The specific loss that prompted this: an annotation the user wrote to themselves."""
    path = existing_config(tmp_path)
    cli.main(["--config", str(path), "init"])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["_comment"] == "tuned for my dense reference corpus - do not change"
    assert data["text_num_ctx"] == 8192


def test_force_replaces_deliberately(tmp_path, capsys):
    path = existing_config(tmp_path)
    code = cli.main(["--config", str(path), "init", "--force"])

    assert code == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "_comment" not in data, "--force means start over"
    assert data["text_num_ctx"] == Config().text_num_ctx


def test_init_writes_a_config_when_there_is_none(tmp_path, capsys):
    path = tmp_path / "winnow.json"
    code = cli.main(["--config", str(path), "init"])

    assert code == 0
    assert path.exists()
    assert "wrote" in capsys.readouterr().out


def test_what_init_writes_loads_back_without_warnings(tmp_path):
    """A starter config that warns on its own next load would be an embarrassment."""
    import warnings

    path = tmp_path / "winnow.json"
    cli.main(["--config", str(path), "init"])

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        loaded = Config.load(path)
    assert loaded.pack == Config().pack


def test_init_writes_every_setting_not_a_subset(tmp_path):
    """A starter config is documentation; a partial one sends people to the source."""
    import dataclasses

    path = tmp_path / "winnow.json"
    cli.main(["--config", str(path), "init"])
    written = set(json.loads(path.read_text(encoding="utf-8")))
    expected = {f.name for f in dataclasses.fields(Config)}
    assert written == expected, f"missing from the starter config: {sorted(expected - written)}"
