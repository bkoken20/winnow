"""A folder of mostly-empty files made the cost gate measure nothing and let the run go.

`index_notes_folder` samples the MEDIAN-sized file, which is the right instinct: real notes
folders spread over an order of magnitude and timing an arbitrary file projects the whole run
badly. But when more than half the files are empty the median IS empty, and then two things
happen at once:

  * timing it measures almost nothing, because there is no text to extract; and
  * `sample_bytes == 0`, so `Projection.scales_by_volume` is false and the projection falls
    back to `unit_seconds * units` -- that same near-zero unit, multiplied.

The projection comes out at roughly zero, the gate is satisfied by a number that describes
none of the work, and the run proceeds. That is the exact promise the README makes about
measuring one real unit before starting, broken by the most ordinary folder there is: one
where some files are placeholders.

Empty files are not exotic. `touch` leaves them, a failed export leaves them, and a notes
folder built up over years has them.

Reported by an external review.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.cost import Projection, RunRefused
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class SlowPerByteLLM:
    """Stands in for a model: the more text it is given, the longer it takes.

    Not a timer trick -- extraction really does scale with volume, and the gate exists
    because of it. A stub that answers instantly whatever it is given cannot show the
    difference between sampling an empty file and sampling a real one.
    """

    def __init__(self, seconds_per_kb: float = 0.05):
        self.seconds_per_kb = seconds_per_kb
        self.calls = 0

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        import time

        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        self.calls += 1
        time.sleep(self.seconds_per_kb * len(body) / 1024)
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
    pipeline.extractor.llm = SlowPerByteLLM()
    return pipeline


def _folder(tmp_path, empty: int, real: int, kb_each: int = 8) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir()
    for i in range(empty):
        (folder / f"empty-{i:03d}.md").write_text("", encoding="utf-8")
    line = "a specific claim about throughput and batching on this hardware\n"
    body = line * ((kb_each * 1024) // len(line))
    for i in range(real):
        (folder / f"real-{i:03d}.md").write_text(body, encoding="utf-8")
    return folder


def test_the_sampled_file_has_something_in_it(tmp_path, capsys):
    """The whole measurement rests on the sample. An empty sample measures nothing."""
    folder = _folder(tmp_path, empty=7, real=5)

    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(folder, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    projection = result["projection"]
    assert projection.sample_bytes > 0, (
        "the median file was empty, so the run was timed on a file with no text in it"
    )


def test_the_projection_still_scales_by_volume(tmp_path, capsys):
    folder = _folder(tmp_path, empty=7, real=5)

    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(folder, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    projection = result["projection"]
    assert projection.total_bytes > 0
    assert projection.scales_by_volume, (
        "projection fell back to unit x file-count, and the unit was an empty file"
    )


def test_a_run_with_real_work_in_it_is_not_projected_at_zero(tmp_path, capsys):
    """160 KB of text takes seconds at this stub's speed, and the estimate must say so.

    Measured before the fix: `unit_seconds=0.00021` over a folder holding 41,600 bytes,
    projected at 2.5 milliseconds. The stub sleeps 0.05 s per KB, so the honest figure for
    160 KB is about eight seconds -- four orders of magnitude apart.
    """
    folder = _folder(tmp_path, empty=7, real=5, kb_each=32)

    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(folder, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    projection = result["projection"]
    assert projection.total_seconds > 1.0, (
        f"160 KB at 0.05 s/KB cannot take {projection.total_seconds:.4f} s -- the estimate "
        "was taken from a file with no text in it"
    )


def test_the_user_is_shown_the_number_when_it_is_large(tmp_path, capsys, monkeypatch):
    """The other half: an estimate nobody is shown is not a gate.

    `gate` returns silently below 120 seconds and `index_notes_folder` never overrides that,
    so reaching the refusal path means lowering the threshold rather than writing megabytes
    of fixture. The defect made this unreachable in the opposite way: the projection was
    near zero, so no folder was ever large enough.
    """
    from winnow import cost, pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "gate",
        lambda projection, accepted: cost.gate(projection, accepted, threshold_seconds=0.5),
    )

    folder = _folder(tmp_path, empty=7, real=5, kb_each=32)
    pipeline = _pipeline(tmp_path)
    try:
        with pytest.raises(RunRefused) as refused:
            pipeline.index_notes_folder(folder, accept_minutes=None)
    finally:
        pipeline.close()
    said = "".join(capsys.readouterr())

    assert "projected run:" in said, f"the number was never shown: {said!r}"
    assert "accept-minutes" in str(refused.value)


def test_an_entirely_empty_folder_is_honest_about_it(tmp_path, capsys):
    """The guard: with nothing to measure, the count-based path is the truthful one."""
    folder = _folder(tmp_path, empty=5, real=0)

    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(folder, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    projection = result["projection"]
    assert projection.total_bytes == 0
    assert not projection.scales_by_volume
    assert result["files"] == 5


def test_a_normal_folder_still_samples_the_median(tmp_path, capsys):
    """The guard: skipping empties must not turn the median into the largest file.

    SIX files, not five. With an odd count the middle index is the middle whichever way the
    list is sorted, so a reversed sort -- sampling the largest file -- survived this test
    unchanged. An even count is the smallest fixture that can tell the two apart.

    The skew is the point: 100..500 and one 20 KB monster is what a real notes folder looks
    like, and timing the monster over-states every run that contains one.
    """
    folder = tmp_path / "notes"
    folder.mkdir()
    for size, name in ((100, "a"), (200, "b"), (300, "c"), (400, "d"), (500, "e"),
                       (20_000, "f")):
        (folder / f"{name}.md").write_text("x" * size, encoding="utf-8")

    pipeline = _pipeline(tmp_path)
    try:
        result = pipeline.index_notes_folder(folder, accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    sampled = result["projection"].sample_bytes
    assert sampled == 400, f"the upper middle of six sorted ascending is 400, got {sampled}"
    assert sampled != 20_000, "the sample was the largest file, so every run is over-stated"


# -- the state that made it possible -----------------------------------------------------


def test_a_projection_cannot_claim_bytes_it_did_not_sample():
    """`sample_bytes=0` with `total_bytes>0` is not a projection, it is a silent fallback.

    The caller has volume to process and no measurement of throughput, so `extraction_
    seconds` quietly reverts to unit x count -- with a unit that measured an empty file.
    Refused at construction so the combination cannot exist rather than be remembered.
    """
    with pytest.raises(ValueError) as raised:
        Projection(unit_seconds=1.0, units=10, sample_bytes=0, total_bytes=100_000)

    assert "sample" in str(raised.value).lower()


def test_the_two_legitimate_shapes_still_build():
    """The guard: file-count projections and volume projections are both real."""
    by_count = Projection(unit_seconds=1.0, units=10)
    assert not by_count.scales_by_volume

    by_volume = Projection(unit_seconds=1.0, units=10, sample_bytes=100, total_bytes=1000)
    assert by_volume.scales_by_volume
