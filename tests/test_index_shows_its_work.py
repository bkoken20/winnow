"""`winnow index` printed a projection, then said nothing until it finished.

The gate exists because indexing a folder is not a five-minute job: it prints "about 34
hours" and asks you to accept it. Then, having told you the run is an afternoon, it produced
no further output at all until every file was done.

    projected run: measured 6.02s for 12.4 KB (2.1 KB/s); 157 files totalling 7.5 MB
    proceeding -- accepted budget covers 58.2 minutes
    <nothing, for 58 minutes>
    indexed 157 files -> 3,412 claims stored

Worse than the ingest case this mirrors, because the gate has just established that the run
is long. A projection is a promise about duration; it is not evidence that anything is still
happening, and the longer the accepted budget the less a user can tell a working run from a
wedged one.

Two silences, not one. The first is before the projection even appears: `index` measures one
real file to project the whole folder, and that measurement is itself a full extraction --
one model call per chunk, on a file chosen for being median-sized. On the corpus this was
built against that is six seconds; on a folder of large documents it is minutes, and it
happens before the tool has said anything whatsoever.

Same shape of fix as the extractor's per-pass progress: a callback, so the pipeline decides
where output goes, and a test can watch the calls rather than a stream.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from winnow import cli
from winnow.config import Config
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _notes(tmp_path, count: int = 6) -> Path:
    """A folder of differently-sized notes, so the sample is not the first or the last."""
    folder = tmp_path / "notes"
    folder.mkdir(parents=True)
    for i in range(count):
        body = "\n".join(
            f"Note {i} sentence {j} reports a throughput of {i * 10 + j} percent."
            for j in range(1 + i * 2)
        )
        (folder / f"note{i:02d}.md").write_text(body, encoding="utf-8")
    return folder


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


def _pipeline(tmp_path) -> Pipeline:
    from winnow.extract import Extractor

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(tmp_path / "corpus.db"),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
            index_extra_passes=[],
        )
    )
    pipeline.extractor = Extractor(
        llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    return pipeline


# -- what the user sees ---------------------------------------------------------------


def test_every_file_is_accounted_for_while_it_runs(tmp_path, capsys, monkeypatch):
    """A run the gate has just called long must keep saying it is alive."""
    _offline(monkeypatch)
    folder = _notes(tmp_path, count=6)

    cli.main(["index", str(folder), "--config", str(_config_file(tmp_path)),
              "--accept-minutes", "600"])
    said = "".join(capsys.readouterr())

    for i in range(6):
        assert f"note{i:02d}.md" in said, (
            f"note{i:02d}.md was indexed and never mentioned while it was happening: {said!r}"
        )


def test_the_progress_says_how_far_through_the_folder_it_is(tmp_path, capsys, monkeypatch):
    """A filename alone does not say whether this is the second file or the last."""
    _offline(monkeypatch)
    folder = _notes(tmp_path, count=6)

    cli.main(["index", str(folder), "--config", str(_config_file(tmp_path)),
              "--accept-minutes", "600"])
    said = "".join(capsys.readouterr())

    positions = re.findall(r"\b(\d+) of (\d+)\b", said)
    assert positions, f"nothing says how far through the folder the run is: {said!r}"
    assert {total for _, total in positions} == {"6"}, positions
    assert sorted(int(n) for n, _ in positions) == [1, 2, 3, 4, 5, 6], (
        f"every file should be counted exactly once, in order: {positions}"
    )


def test_the_measured_file_is_named_on_screen(tmp_path, capsys):
    """The first silence is BEFORE the projection, and it is a full extraction.

    `index` times one real file to project the folder. Nothing had said so, so the run's
    first observable act came after that file had already been extracted.

    The line must NAME the file. An earlier version of this checked only that the callback
    received a path, which stays true when the printed line says "measuring one file to
    project the run" and names nothing -- the mutation survived the whole suite.
    """
    folder = _notes(tmp_path, count=6)
    pipeline = _pipeline(tmp_path)
    try:
        pipeline.index_notes_folder(folder, accept_minutes=600)
    finally:
        pipeline.close()
    said = "".join(capsys.readouterr())

    lines = [ln for ln in said.splitlines() if ln.strip()]
    measuring = next((ln for ln in lines if "measur" in ln.lower()), None)
    assert measuring is not None, f"the measurement is never announced: {said!r}"
    assert any(p.name in measuring for p in folder.iterdir()), (
        f"the line does not say WHICH file is being measured: {measuring!r}"
    )


def test_the_measurement_is_announced_before_it_runs(tmp_path):
    """Announcing it afterwards describes the silence instead of filling it.

    Ordering against the projection line cannot detect this: called directly, `gate` prints
    nothing below 120 seconds, so there is no projection line to come after and the
    comparison holds no matter where the announcement sits. Ordered against the WORK
    instead -- the model calls the measurement is made of.
    """
    order = []
    folder = _notes(tmp_path, count=6)
    pipeline = _pipeline(tmp_path)

    class RecordingLLM(LineClaimsLLM):
        def generate(self, *args, **kwargs):
            order.append("model call")
            return super().generate(*args, **kwargs)

    pipeline.extractor.llm = RecordingLLM()
    try:
        pipeline.index_notes_folder(
            folder,
            accept_minutes=600,
            progress=lambda **kw: order.append(f"announce {kw['stage']}"),
        )
    finally:
        pipeline.close()

    assert order[0] == "announce measure", (
        f"the measurement ran before anything said it was happening: {order[:4]}"
    )
    assert order[1] == "model call", order[:4]


# -- the pipeline reports through a callback ------------------------------------------


def test_the_callback_is_told_the_position_and_the_file(tmp_path):
    seen = []
    folder = _notes(tmp_path, count=6)
    pipeline = _pipeline(tmp_path)
    try:
        pipeline.index_notes_folder(
            folder, accept_minutes=600, progress=lambda **kw: seen.append(kw)
        )
    finally:
        pipeline.close()

    indexed = [s for s in seen if s.get("stage") == "index"]
    assert [s["number"] for s in indexed] == [1, 2, 3, 4, 5, 6]
    assert all(s["total"] == 6 for s in indexed)
    assert sorted(Path(s["path"]).name for s in indexed) == [
        f"note{i:02d}.md" for i in range(6)
    ]

    measured = [s for s in seen if s.get("stage") == "measure"]
    assert len(measured) == 1, f"exactly one file is measured for the projection: {measured}"
    assert Path(measured[0]["path"]).name.startswith("note")


def test_the_sample_is_counted_once_not_twice(tmp_path):
    """The measured file is committed rather than re-indexed, and is still one of the N.

    It is removed from `files` after the gate, so a naive `enumerate` over what remains
    counts it out of the run entirely and reports 5 of 5 for six files.
    """
    seen = []
    folder = _notes(tmp_path, count=6)
    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(
            folder, accept_minutes=600, progress=lambda **kw: seen.append(kw)
        )
    finally:
        pipeline.close()

    indexed = [s for s in seen if s.get("stage") == "index"]
    names = [Path(s["path"]).name for s in indexed]
    assert len(names) == len(set(names)) == result["files"] == 6, names

    measured = [s for s in seen if s.get("stage") == "measure"][0]
    assert Path(measured["path"]).name in names, (
        "the measured file is one of the files indexed, and must be counted among them"
    )


def test_a_refused_run_announces_nothing_it_did_not_do(tmp_path, monkeypatch):
    """The gate refuses AFTER the measurement. Nothing may be reported as indexed.

    The refusal has to be a real one. `gate` returns without a word below 120 seconds, so
    a folder of six stub notes projects to under a second and `--accept-minutes 0` has
    nothing to refuse -- the first version of this test asserted a raise that could never
    happen. The sampled unit is made genuinely slow instead, which is what a folder of
    large documents does on its own.
    """
    from winnow import pipeline as pipeline_module
    from winnow.cost import RunRefused

    real_time_one = pipeline_module.time_one
    monkeypatch.setattr(
        pipeline_module,
        "time_one",
        lambda fn, *a, **k: (real_time_one(fn, *a, **k)[0], 600.0),
    )

    seen = []
    folder = _notes(tmp_path, count=6)
    pipeline = _pipeline(tmp_path)
    try:
        with pytest.raises(RunRefused):
            pipeline.index_notes_folder(
                folder, accept_minutes=0.0, progress=lambda **kw: seen.append(kw)
            )
    finally:
        pipeline.close()

    assert [s for s in seen if s.get("stage") == "measure"], (
        "the measurement happened and should have been announced"
    )
    assert not [s for s in seen if s.get("stage") == "index"], (
        f"a refused run announced files it never indexed: {seen}"
    )


def test_progress_does_not_change_what_is_indexed(tmp_path):
    quiet_folder = _notes(tmp_path / "a", count=6)
    watched_folder = _notes(tmp_path / "b", count=6)

    quiet = _pipeline(tmp_path / "qa")
    try:
        a = quiet.index_notes_folder(quiet_folder, accept_minutes=600)
    finally:
        quiet.close()

    watched = _pipeline(tmp_path / "wb")
    try:
        b = watched.index_notes_folder(
            watched_folder, accept_minutes=600, progress=lambda **kw: None
        )
    finally:
        watched.close()

    assert a["files"] == b["files"] == 6
    assert a["claims"] == b["claims"]


def test_the_narrative_is_on_one_stream(tmp_path, capsys, monkeypatch):
    """Progress is stderr, like every other announcement; results stay on stdout."""
    _offline(monkeypatch)
    folder = _notes(tmp_path, count=6)

    cli.main(["index", str(folder), "--config", str(_config_file(tmp_path)),
              "--accept-minutes", "600"])
    out, err = capsys.readouterr()

    assert "note00.md" in err, f"progress belongs on stderr: {err!r}"
    assert "note00.md" not in out, (
        f"progress on stdout would interleave with the result lines: {out!r}"
    )
