"""The same file, spelled differently, must be recognised as the same file.

`source_id_for` hashes `path.resolve()`, but `add_source` stores `str(path)` exactly as it
arrived and `skip_known` compares those raw strings. So the identity of a source and the
memory of having processed it disagree:

    winnow index ./notes        stores "notes\\a.md"
    winnow index C:\\...\\notes   stores "C:\\...\\notes\\a.md" -- a different string

The second run re-extracts every file, at full model cost, and because the source ID is the
same it then REPLACES the rows it just duplicated the work for. On Windows the same happens
between `Notes` and `notes`.

Reported by an external review as fragile path matching.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def __init__(self):
        self.calls = 0

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        self.calls += 1
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _pipeline(tmp_path) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        index_extra_passes=[],
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor.llm = LineClaimsLLM()
    return pipeline


@pytest.fixture
def notes(tmp_path) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "a.md").write_text("throughput is bandwidth bound", encoding="utf-8")
    (folder / "b.md").write_text("batching raises utilisation", encoding="utf-8")
    return folder


def test_a_relative_and_an_absolute_spelling_are_the_same_folder(notes, tmp_path, monkeypatch, capsys):
    absolute = _pipeline(tmp_path)
    try:
        first = absolute.index_notes_folder(notes, accept_minutes=600)
    finally:
        absolute.close()
    capsys.readouterr()
    assert first["files"] == 2

    monkeypatch.chdir(tmp_path)
    relative = _pipeline(tmp_path)
    try:
        again = relative.index_notes_folder(Path("notes"), accept_minutes=600)
    finally:
        relative.close()
    capsys.readouterr()

    assert again["files"] == 0, (
        f"the same folder under a different spelling was re-indexed at full model cost: {again}"
    )


def test_the_stored_path_is_the_resolved_one(notes, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pipeline = _pipeline(tmp_path)
    try:
        pipeline.index_notes_folder(Path("notes"), accept_minutes=600)
        stored = pipeline.store.source_paths("ai_tooling")
    finally:
        pipeline.close()
    capsys.readouterr()

    assert stored, "nothing was recorded"
    for path in stored:
        assert Path(path).is_absolute(), (
            f"{path!r} was stored as written rather than resolved, so the same file under "
            "another spelling will not match it"
        )


@pytest.mark.skipif(
    not (Path(__file__).parent / "TEST_CASE_PROBE").exists()
    and os.path.exists(str(Path(__file__)).upper()) is False,
    reason="filesystem is case-sensitive",
)
def test_a_different_case_is_the_same_folder(notes, tmp_path, capsys):
    """Windows and macOS both treat `Notes` and `notes` as one folder."""
    pipeline = _pipeline(tmp_path)
    try:
        pipeline.index_notes_folder(notes, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    shouted = notes.parent / notes.name.upper()
    second = _pipeline(tmp_path)
    try:
        again = second.index_notes_folder(shouted, accept_minutes=600)
    finally:
        second.close()
    capsys.readouterr()

    assert again["files"] == 0, f"case alone made it a different folder: {again}"


def test_a_genuinely_new_file_is_still_indexed(notes, tmp_path, capsys):
    """The guard: normalising must not make everything look already-done."""
    pipeline = _pipeline(tmp_path)
    try:
        pipeline.index_notes_folder(notes, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    (notes / "c.md").write_text("prefix caching helps long prompts", encoding="utf-8")

    second = _pipeline(tmp_path)
    try:
        again = second.index_notes_folder(notes, accept_minutes=600)
    finally:
        second.close()
    capsys.readouterr()

    assert again["files"] == 1, f"the new file should be the only work: {again}"
