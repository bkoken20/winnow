"""A setting of the wrong type is bad input, and bad input has an exit code.

`Config.load` checks two settings by name -- `judge_location` and `embed_backend` -- and
nothing else. Every other value goes into the dataclass exactly as JSON produced it and fails
later, somewhere in the middle of a run, as a Python error nobody can act on. Ten of these
were reproduced against the real CLI:

    text_num_ctx: "32768"     TypeError: unsupported operand type(s) for -: 'str' and 'int'
    text_num_ctx: null        TypeError: unsupported operand type(s) for -: 'NoneType' and 'int'
    chunk_chars: "2000"       TypeError: '<' not supported between instances of 'int' and 'str'
    duplicate_threshold: "0.9"  TypeError: '<=' not supported between 'str' and 'int'
    corpus_path: 5            TypeError: argument should be a str or an os.PathLike object
    packs_root: 5             the same
    notes_path: 5             the same
    pack: 5                   TypeError: unsupported operand type(s) for /: 'WindowsPath' and 'int'
    ollama_host: 5            AttributeError: 'int' object has no attribute 'decode'
    index_extra_passes: 1000  TypeError: 'int' object is not iterable

All of it contradicts the exit-code table, which promises 2 for bad input.

The fix belongs at the boundary, NOT in `cli._run`. The review suggests catching `TypeError`
and `ValueError` there; `_run`'s own docstring refuses that, and rightly -- those are the
exceptions a genuine bug raises, and flattening them into "bad input" would hide the next
real defect behind a tidy message. A value that came out of the user's file is checked where
it enters.

A directly constructed `Config(...)` is deliberately NOT validated: the privacy checks must
stay testable against values that cannot be loaded, which is how `is_fully_local` is proved
to fail closed.

Reported by an external review.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from winnow import cli
from winnow.config import Config, InvalidConfiguration

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"

# A value of the WRONG type for each declared type, used to prove every field is checked.
WRONG_FOR = {
    "str": 5,
    "int": "32768",
    "float": "0.9",
    "list": 1000,
    "dict": 5,
}


def _write(tmp_path, **overrides) -> Path:
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


def _declared_kind(annotation) -> str:
    """`int`, `str`, `float`, `list[int]` and `dict` are all this dataclass uses."""
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    for kind in ("list", "dict", "str", "float", "int"):
        if text.startswith(kind):
            return kind
    return ""


ALL_FIELDS = [(f.name, _declared_kind(f.type)) for f in fields(Config)]


def test_every_field_declares_a_type_this_test_understands():
    """Guard the guard: an annotation nobody recognises would silently test nothing."""
    unknown = [name for name, kind in ALL_FIELDS if not kind]
    assert not unknown, f"these fields have annotations this test cannot read: {unknown}"


@pytest.mark.parametrize("name, kind", ALL_FIELDS, ids=[n for n, _ in ALL_FIELDS])
def test_a_value_of_the_wrong_type_is_refused(tmp_path, name, kind):
    """Derived from the dataclass, so a field added later is covered the day it appears."""
    path = _write(tmp_path, **{name: WRONG_FOR[kind]})

    with pytest.raises(InvalidConfiguration) as raised:
        Config.load(path)

    message = str(raised.value)
    assert name in message, f"which setting? {message!r}"
    assert "winnow.json" in message, f"which file? {message!r}"


@pytest.mark.parametrize(
    "setting, value",
    [
        ("text_num_ctx", None),
        ("corpus_path", None),
        ("ingest_extra_passes", None),
    ],
    ids=["text_num_ctx", "corpus_path", "ingest_extra_passes"],
)
def test_null_is_not_a_value(tmp_path, setting, value):
    """JSON `null` is the easiest way to half-delete a setting, and it reached the code."""
    with pytest.raises(InvalidConfiguration):
        Config.load(_write(tmp_path, **{setting: value}))


def test_true_is_not_a_number(tmp_path):
    """`bool` is a subclass of `int`, so a plain isinstance check lets `true` through."""
    with pytest.raises(InvalidConfiguration):
        Config.load(_write(tmp_path, text_num_ctx=True))


def test_a_list_of_the_wrong_thing_is_refused(tmp_path):
    with pytest.raises(InvalidConfiguration) as raised:
        Config.load(_write(tmp_path, index_extra_passes=["1000"]))

    assert "index_extra_passes" in str(raised.value)


# -- ranges, which a type cannot express -------------------------------------------------


@pytest.mark.parametrize(
    "setting", ["text_num_ctx", "vision_num_ctx", "judge_num_ctx", "chunk_chars",
                "frame_every_seconds", "max_frames"],
)
def test_a_size_of_zero_is_refused(tmp_path, setting):
    """Zero is the shape of a half-edited file, and every one of these is a size."""
    with pytest.raises(InvalidConfiguration) as raised:
        Config.load(_write(tmp_path, **{setting: 0}))

    assert setting in str(raised.value)


@pytest.mark.parametrize(
    "group, allowed",
    [("POSITIVE_SETTINGS", {"int"}), ("UNIT_INTERVAL_SETTINGS", {"int", "float"})],
)
def test_every_range_checked_setting_is_a_number(group, allowed):
    """Found by walking the validator, not by running it.

    The range checks compare the file's value with 0 directly. They are safe only because
    the type check above has already rejected a non-number for every name in these tuples --
    which holds only while every name in them is a numeric field. Nothing enforces that, and
    the day one of them becomes a string the comparison raises the same TypeError this whole
    validator exists to prevent.

    Verified by disabling the type check and calling the validator: `max_frames: "20"` gives
    `TypeError: '<=' not supported between instances of 'str' and 'int'`.
    """
    from winnow import config as module

    for name in getattr(module, group):
        spec = Config.__dataclass_fields__.get(name)
        assert spec is not None, f"{group} names {name!r}, which is not a setting"

        kind = _declared_kind(spec.type)
        assert kind in allowed, (
            f"{group} names {name!r}, declared as {spec.type!r}. The range check compares "
            f"it with 0, so it must be a number or that comparison raises TypeError."
        )


def test_a_similarity_threshold_outside_zero_to_one_is_refused(tmp_path):
    """5.0 was accepted in silence -- and no cosine reaches it, so nothing is ever a duplicate.

    Not a traceback: a wrong answer, delivered confidently, with the dedupe step disabled
    and no way to tell from the output.
    """
    for value in (5.0, -0.5, 1.5):
        with pytest.raises(InvalidConfiguration) as raised:
            Config.load(_write(tmp_path, duplicate_threshold=value))
        assert "duplicate_threshold" in str(raised.value)


def test_a_whole_number_is_a_valid_similarity(tmp_path):
    """JSON writes 1, not 1.0. Refusing it would refuse a correct file."""
    config = Config.load(_write(tmp_path, duplicate_threshold=1))
    assert config.duplicate_threshold == 1

    config = Config.load(_write(tmp_path, duplicate_threshold=0))
    assert config.duplicate_threshold == 0


def test_true_is_not_a_similarity_either(tmp_path):
    """`bool` is an `int`, and `True <= 1` is happily True."""
    with pytest.raises(InvalidConfiguration):
        Config.load(_write(tmp_path, duplicate_threshold=True))


def test_an_extra_pass_of_zero_chunk_size_is_refused(tmp_path):
    with pytest.raises(InvalidConfiguration):
        Config.load(_write(tmp_path, ingest_extra_passes=[1000, 0]))


# -- the guarantee, end to end -----------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"text_num_ctx": "32768"},
        {"text_num_ctx": None},
        {"chunk_chars": "2000"},
        {"duplicate_threshold": "0.9"},
        {"corpus_path": 5},
        {"packs_root": 5},
        {"notes_path": 5},
        {"pack": 5},
        {"ollama_host": 5},
        {"index_extra_passes": 1000},
    ],
    ids=lambda o: next(iter(o)) + "=" + repr(next(iter(o.values()))),
)
def test_the_cli_answers_with_exit_two_and_no_traceback(tmp_path, capsys, overrides):
    path = _write(tmp_path, **overrides)

    code = cli.main(["status", "--config", str(path)])
    said = "".join(capsys.readouterr())

    assert "Traceback" not in said, said
    assert code == 2, f"README documents 2 for bad input, got {code}: {said!r}"
    assert next(iter(overrides)) in said, f"name the setting: {said!r}"


# -- the mirror --------------------------------------------------------------------------


def test_the_defaults_survive_a_round_trip(tmp_path):
    """The guard: validation that refuses correct settings is worse than none."""
    path = tmp_path / "winnow.json"
    Config().save(path)

    loaded = Config.load(path)
    assert loaded == Config()


def test_a_reasonable_configuration_still_loads(tmp_path):
    path = _write(
        tmp_path,
        text_num_ctx=8192,
        chunk_chars=1000,
        duplicate_threshold=0.0,
        ingest_extra_passes=[500],
        index_extra_passes=[],
        notes_path="",
        judge_model="",
    )
    config = Config.load(path)

    assert config.text_num_ctx == 8192
    assert config.duplicate_threshold == 0.0
    assert config.ingest_extra_passes == [500]
    assert config.index_extra_passes == []


def test_a_directly_built_config_is_not_validated():
    """Deliberate. The privacy checks are proved to fail closed on values load refuses."""
    odd = Config(judge_location="cloutd", text_num_ctx="32768")

    assert odd.judge_location == "cloutd"
    assert not odd.is_fully_local
