"""`winnow index` reported success over a folder it had read nothing from.

Point it at a folder of `.rst` notes — or `.org`, or `.csv`, or files with no extension at
all — and it says:

    nothing new to index          exit 0

Nothing was indexed, nothing was wrong, and nothing said which. That is a **silent empty
result**, which is the exact failure the tool's own documentation promises it does not
produce: "a video with no captions is a stop, not a silent empty result." `ingest` honours
that for a single file — `winnow ingest notes.rst` exits 2 and says so. `index` did not, for
a folder.

Three different situations collapsed into one `files == 0`:

    the folder holds nothing this can read     -> should be an error, naming what it found
    the folder is empty                        -> should say the folder is empty
    everything in it is already indexed        -> "nothing new to index" is exactly right

Only the third deserves exit 0 and that message. The first is the one that bites: a user
whose notes are in a format Winnow does not read is told the run succeeded.

Found while fact-checking a sentence written for an article about the tool.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow import cli
from winnow.config import Config
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"
BODY = "Throughput on this hardware is bandwidth bound, not compute bound."


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _config_file(tmp_path) -> Path:
    path = tmp_path / "winnow.json"
    path.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(tmp_path / "corpus.db"),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
                "index_extra_passes": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _offline(monkeypatch) -> None:
    from winnow.extract import Extractor

    real_build = Pipeline.build

    def build_with_stub(config):
        pipeline = real_build(config)
        pipeline.extractor = Extractor(
            llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
        )
        return pipeline

    monkeypatch.setattr(Pipeline, "build", staticmethod(build_with_stub))


@pytest.mark.parametrize("suffix", [".rst", ".org", ".csv", ".log", ""])
def test_a_folder_of_unreadable_notes_is_not_a_success(tmp_path, capsys, monkeypatch, suffix):
    """The whole folder is prose and none of it is read. That is not 'nothing new'."""
    notes = tmp_path / "notes"
    notes.mkdir()
    for i in range(3):
        (notes / f"a{i}{suffix}").write_text(BODY, encoding="utf-8")

    _offline(monkeypatch)
    code = cli.main(["index", str(notes), "--config", str(_config_file(tmp_path))])
    said = "".join(capsys.readouterr())

    assert code == 2, f"reporting success over a folder it read nothing from: {said!r}"
    assert "nothing new to index" not in said, (
        f"'nothing new' means everything is already stored, which is not what happened: {said!r}"
    )
    assert ".md" in said or ".txt" in said, (
        f"say which extensions it does read, or the user cannot act: {said!r}"
    )


def test_it_names_what_it_found(tmp_path, capsys, monkeypatch):
    """A user with 400 .rst files needs to see .rst, not a list of what was wanted."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "one.rst").write_text(BODY, encoding="utf-8")
    (notes / "two.rst").write_text(BODY, encoding="utf-8")

    _offline(monkeypatch)
    cli.main(["index", str(notes), "--config", str(_config_file(tmp_path))])
    said = "".join(capsys.readouterr())

    assert ".rst" in said, f"name what is actually in the folder: {said!r}"


def test_a_dot_directory_is_not_someone_s_notes(tmp_path, capsys, monkeypatch):
    """`.venv` and `.git` are tool directories, and their contents are not your reading.

    Measured before the fix, on a folder holding one note under version control: 27 files
    seen, and `notes/.venv/lib/site-packages/somepkg/README.md` in the list Winnow would
    INDEX. A package README costs a model call and then enters the corpus as prior
    knowledge, so a genuinely new claim can be judged "already known" against documentation
    the user has never read.
    """
    notes = tmp_path / "notes"
    (notes / ".venv" / "lib" / "somepkg").mkdir(parents=True)
    (notes / ".git" / "hooks").mkdir(parents=True)

    (notes / "mine.md").write_text(BODY, encoding="utf-8")
    (notes / ".venv" / "lib" / "somepkg" / "README.md").write_text(
        "An unrelated claim about installing a package.", encoding="utf-8"
    )
    (notes / ".git" / "hooks" / "pre-commit.sample").write_text("#!/bin/sh", encoding="utf-8")

    _offline(monkeypatch)
    code = cli.main(
        ["index", str(notes), "--config", str(_config_file(tmp_path)),
         "--accept-minutes", "600"]
    )
    said = "".join(capsys.readouterr())

    assert code == 0, said
    assert "indexed 1 files" in said, (
        f"only the user's own note is theirs to index: {said!r}"
    )
    assert ".sample" not in said, (
        f"git's internals are not a skipped note worth reporting: {said!r}"
    )


def test_a_folder_that_is_only_tool_directories_is_empty_of_notes(
    tmp_path, capsys, monkeypatch
):
    """The mirror: hiding them must not turn 'nothing readable' into 'success'."""
    notes = tmp_path / "notes"
    (notes / ".git" / "hooks").mkdir(parents=True)
    (notes / ".git" / "hooks" / "pre-commit.sample").write_text("#!/bin/sh", encoding="utf-8")

    _offline(monkeypatch)
    code = cli.main(["index", str(notes), "--config", str(_config_file(tmp_path))])
    said = "".join(capsys.readouterr()).lower()

    assert code == 2
    assert "empty" in said, f"nothing of the user's is in there: {said!r}"


def test_an_empty_folder_says_it_is_empty(tmp_path, capsys, monkeypatch):
    """Distinct from both the others, and the message should not claim otherwise."""
    notes = tmp_path / "notes"
    notes.mkdir()

    _offline(monkeypatch)
    code = cli.main(["index", str(notes), "--config", str(_config_file(tmp_path))])
    said = "".join(capsys.readouterr()).lower()

    assert code == 2
    assert "empty" in said or "no files" in said, said


def test_a_mixed_folder_indexes_what_it_can_and_mentions_the_rest(
    tmp_path, capsys, monkeypatch
):
    """The common real case, and it must not become an error."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "read.md").write_text(BODY, encoding="utf-8")
    (notes / "skipped.rst").write_text(BODY, encoding="utf-8")

    _offline(monkeypatch)
    code = cli.main(
        ["index", str(notes), "--config", str(_config_file(tmp_path)),
         "--accept-minutes", "600"]
    )
    said = "".join(capsys.readouterr())

    assert code == 0, said
    assert "1 files" in said or "indexed 1" in said, said
    assert ".rst" in said, f"the skipped file must still be mentioned: {said!r}"


def test_nothing_new_still_means_nothing_new(tmp_path, capsys, monkeypatch):
    """The guard: the one case that legitimately exits 0 must keep doing so."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text(BODY, encoding="utf-8")
    config = _config_file(tmp_path)

    _offline(monkeypatch)
    first = cli.main(["index", str(notes), "--config", str(config), "--accept-minutes", "600"])
    capsys.readouterr()
    second = cli.main(["index", str(notes), "--config", str(config), "--accept-minutes", "600"])
    said = "".join(capsys.readouterr())

    assert first == 0
    assert second == 0, said
    assert "nothing new to index" in said, said


def test_the_pipeline_reports_the_two_cases_apart(tmp_path, capsys):
    """The distinction lives in the result, not in the CLI guessing from a zero."""
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    (unreadable / "a.rst").write_text(BODY, encoding="utf-8")

    empty = tmp_path / "empty"
    empty.mkdir()

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(tmp_path / "corpus.db"),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
        )
    )
    try:
        a = pipeline.index_notes_folder(unreadable, accept_minutes=600)
        b = pipeline.index_notes_folder(empty, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    assert a["files"] == 0 and b["files"] == 0
    assert a["unreadable"] == [".rst"], a
    assert b["unreadable"] == [], b
