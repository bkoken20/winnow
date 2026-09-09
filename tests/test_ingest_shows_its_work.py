"""An ingest ran for minutes and said nothing about how long, or how far along.

The cost gate was built for `index` and `rejudge`, on the reasoning that an ingest is one
item and therefore short. This project's own experiment disagrees —
`experiments/TWO_PASS.md` line 140:

    ingest — one 25-minute talk | 1.7 min | 3.4 min | 4.5 min

Three passes is the DEFAULT for ingest, so 4.5 minutes is the ordinary case, plus the fetch.
What the user saw was `destination:`, `transcript:`, and then nothing at all until the claims
appeared. Long enough to wonder whether it had hung — the same complaint the last review made
about yt-dlp swallowing its progress, one step further down the same pipeline.

No gate here. A gate on four minutes is ceremony people learn to click through, which is
exactly what the threshold in `cost.gate` exists to avoid. What was missing is not permission
but information: how far along, and what it cost.

The extractor takes a callback rather than printing. It is a library: the pipeline decides
where output goes, and a test can watch the calls without capturing a stream.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from winnow import cli
from winnow.cost import human_seconds
from winnow.extract import Extractor
from winnow.packs import find_pack
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"
TALK = "\n".join(
    f"Subject {i} changes throughput by roughly {i + 3} percent on consumer hardware."
    for i in range(40)
)


class LineClaimsLLM:
    def __init__(self):
        self.calls = 0

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        self.calls += 1
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _config_file(tmp_path, **overrides) -> Path:
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


def _offline(monkeypatch) -> None:
    real_build = Pipeline.build

    def build_with_stub(config):
        pipeline = real_build(config)
        pipeline.extractor = Extractor(
            llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
        )
        return pipeline

    monkeypatch.setattr(Pipeline, "build", staticmethod(build_with_stub))


def _talk(tmp_path) -> Path:
    path = tmp_path / "talk.txt"
    path.write_text(TALK, encoding="utf-8")
    return path


# -- what the user sees ------------------------------------------------------------------


def test_a_finished_ingest_says_what_it_cost(tmp_path, capsys, monkeypatch):
    _offline(monkeypatch)
    cli.main(["ingest", str(_talk(tmp_path)), "--config", str(_config_file(tmp_path))])
    said = "".join(capsys.readouterr())

    # On the summary line itself, not merely somewhere in the output -- a duration that
    # appears in a warning or a claim's text would satisfy a whole-output search while the
    # run still ended without saying what it cost.
    line = next(ln for ln in said.splitlines() if "claims after de-duplication" in ln)
    assert re.search(
        r"\bin (under a second|\d+(\.\d+)? (seconds?|minutes?|hours?))$", line
    ), f"the run ended without saying how long it took: {line!r}"


def test_each_extraction_pass_is_announced(tmp_path, capsys, monkeypatch):
    """Three passes over a long transcript is minutes with nothing on screen."""
    _offline(monkeypatch)
    config = _config_file(tmp_path, ingest_extra_passes=[1000, 4000])

    cli.main(["ingest", str(_talk(tmp_path)), "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert said.count("pass 1 of 3") == 1, said
    assert said.count("pass 2 of 3") == 1, said
    assert said.count("pass 3 of 3") == 1, said


def test_the_passes_announced_are_the_passes_configured(tmp_path, capsys, monkeypatch):
    """One pass configured, one pass announced -- not the ingest default."""
    _offline(monkeypatch)
    config = _config_file(tmp_path, ingest_extra_passes=[])

    cli.main(["ingest", str(_talk(tmp_path)), "--config", str(config)])
    said = "".join(capsys.readouterr())

    assert "pass 1 of 1" in said, said
    assert "of 3" not in said, said


def test_the_progress_says_how_much_work_the_pass_is(tmp_path, capsys, monkeypatch):
    """"pass 2 of 3" alone does not say whether that is ten seconds or two minutes."""
    _offline(monkeypatch)
    cli.main(["ingest", str(_talk(tmp_path)), "--config", str(_config_file(tmp_path))])
    said = "".join(capsys.readouterr())

    line = next(ln for ln in said.splitlines() if "pass 1 of" in ln)
    # A count of work units -- "2 model calls", "9 chunks". Not "2000-character chunks",
    # which is the SIZE of the work and says nothing about how much of it there is.
    assert re.search(r"\b\d+\s+(?:\w+\s+)?(?:calls?|chunks?)\b", line), (
        f"say how many model calls the pass is, not just its number: {line!r}"
    )


# -- the extractor stays a library --------------------------------------------------------


def test_the_extractor_is_silent_without_a_callback(tmp_path, capsys):
    """It is a library. Where output goes is the pipeline's decision, not its own."""
    extractor = Extractor(
        llm=LineClaimsLLM(),
        model="fake",
        num_ctx=32768,
        pack=find_pack("ai_tooling", PACKS_ROOT),
        extra_passes=(1000,),
    )
    extractor.extract(TALK, "sid")
    said = "".join(capsys.readouterr())

    assert said == "", f"the extractor printed on its own: {said!r}"


def test_the_callback_is_told_the_pass_and_the_size(tmp_path):
    seen = []
    extractor = Extractor(
        llm=LineClaimsLLM(),
        model="fake",
        num_ctx=32768,
        pack=find_pack("ai_tooling", PACKS_ROOT),
        chunk_chars=2000,
        extra_passes=(1000,),
    )
    extractor.extract(TALK, "sid", progress=lambda **kw: seen.append(kw))

    assert [s["number"] for s in seen] == [1, 2]
    assert [s["total"] for s in seen] == [2, 2]
    assert [s["chunk_chars"] for s in seen] == [2000, 1000]
    assert all(s["chunks"] > 0 for s in seen)


def test_restructuring_the_loop_did_not_change_what_is_extracted(tmp_path):
    """The passes were one flattened comprehension. Announcing them must not reorder them.

    Same claims, same order, same ids -- the only difference is that something is told
    where one pass ends and the next begins.
    """
    pack = find_pack("ai_tooling", PACKS_ROOT)
    quiet = Extractor(llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pack,
                      chunk_chars=2000, extra_passes=(1000, 4000))
    watched = Extractor(llm=LineClaimsLLM(), model="fake", num_ctx=32768, pack=pack,
                        chunk_chars=2000, extra_passes=(1000, 4000))

    a = quiet.extract(TALK, "sid")
    b = watched.extract(TALK, "sid", progress=lambda **kw: None)

    assert [c.id for c in a] == [c.id for c in b]
    assert [c.text for c in a] == [c.text for c in b]
    assert quiet.llm.calls == watched.llm.calls


def test_one_claim_found_by_three_passes_is_stored_once(tmp_path):
    """`seen` spans the passes, and that is what keeps the loop inside one call.

    Passes exist to cut the same text at different boundaries, so the SAME claim comes back
    from several of them on purpose. Measured on a 30-paragraph transcript at 2,000 / 1,000
    / 4,000 characters: shared `seen` returns 30 claims, a `seen` per pass returns 90, of
    which 60 are exact duplicates -- and each duplicate then costs an embedding, a judge
    call and a row in the corpus, which is the tool reporting the same thing three times.

    This is the reason the announcement is a callback instead of the pipeline driving one
    `extract` call per pass, which would have needed no new parameter at all.
    """
    extractor = Extractor(
        llm=LineClaimsLLM(),
        model="fake",
        num_ctx=32768,
        pack=find_pack("ai_tooling", PACKS_ROOT),
        chunk_chars=2000,
        extra_passes=(1000, 4000),
    )
    claims = extractor.extract(TALK, "sid")

    assert len(claims) == len({c.id for c in claims}), (
        f"{len(claims) - len({c.id for c in claims})} claims are repeats of one another; "
        "de-duplication is not spanning the passes"
    )
    assert extractor.llm.calls > len(claims) / 10, "the passes did not actually all run"


def test_the_size_announced_is_the_size_it_chunked_at(tmp_path):
    """A small context window caps the chunk, and the report must follow the code.

    Announcing the size that was ASKED for would describe a run that did not happen, and
    this is exactly where a user needs the truth: the pass they configured at 4,000 is not
    the pass that ran, and nothing else would tell them.
    """
    from winnow.extract import context_capacity_chars, split_text

    num_ctx = 3500
    capacity = context_capacity_chars(num_ctx)
    assert capacity == 3200, capacity  # (3500 - 1200 - 1500) * 4

    seen = []
    extractor = Extractor(
        llm=LineClaimsLLM(),
        model="fake",
        num_ctx=num_ctx,
        pack=find_pack("ai_tooling", PACKS_ROOT),
        chunk_chars=2000,
        extra_passes=(4000,),
    )
    extractor.extract(TALK, "sid", progress=lambda **kw: seen.append(kw))

    assert [s["chunk_chars"] for s in seen] == [2000, 3200], (
        f"pass 2 was configured at 4000 but can only chunk at {capacity}: {seen}"
    )
    assert seen[1]["chunks"] == len(split_text(TALK, 3200)), (
        "the count announced is not the number of chunks the pass will actually make"
    )


# -- one way of saying a duration ---------------------------------------------------------


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.04, "under a second"),
        (0.4, "under a second"),
        (0.999, "under a second"),
        (3, "3 seconds"),
        (89, "89 seconds"),
        (150, "2.5 minutes"),
        (7200, "2.0 hours"),
    ],
)
def test_a_duration_is_written_one_way(seconds, expected):
    assert human_seconds(seconds) == expected


@pytest.mark.parametrize(
    "unit_seconds, units",
    [
        (0.4, 1),  # under a second
        (3.0, 1),  # whole seconds
        (30.0, 5),  # minutes
        (1440.0, 5),  # hours
        (89.0, 1),  # either side of the 90-second boundary
        (90.0, 1),
        (5400.0, 1),  # and of the hour boundary
    ],
)
def test_the_projection_uses_the_same_formatter(unit_seconds, units):
    """Two ways of writing a duration is two things to keep in step. There is one.

    Parametrised across every branch, because agreement at a single value cannot detect a
    duplicate implementation -- only one that disagrees AT THAT VALUE. Measured: a copy of
    the old body reinstated inside `Projection.human`, missing both the hours branch and
    the sub-second branch, SURVIVED the whole 806-test suite while this asserted agreement
    at 150 seconds alone, which is a value the two render identically.
    """
    from winnow.cost import Projection

    projection = Projection(unit_seconds=unit_seconds, units=units)
    assert projection.human() == human_seconds(projection.total_seconds)
