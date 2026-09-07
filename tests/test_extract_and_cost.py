"""Extraction plumbing and the cost gate."""

import pytest

from winnow.cost import Projection, RunRefused, accepted_by_flag, gate
from winnow.extract import (
    DEFAULT_CHUNK_CHARS,
    Extractor,
    chunk_size_for,
    context_capacity_chars,
    parse_claims_json,
    split_text,
)
from winnow.packs import Pack


# -- chunking ------------------------------------------------------------------


def test_chunk_size_does_not_grow_with_the_context_window():
    """The size that FITS is not the size that WORKS.

    Measured (experiments/CHUNK_SIZE.md): handing a 14B model a whole 47 KB document
    returned 24 distinct claims covering 4% of what the tested settings found between them,
    while 2,000-character chunks returned 275 covering 44%, with a 0-3% duplicate rate at
    every size. A bigger context window is not a reason to send a bigger chunk.
    """
    assert chunk_size_for(32_768) == chunk_size_for(131_072) == DEFAULT_CHUNK_CHARS


def test_context_capacity_still_scales_with_the_window():
    assert context_capacity_chars(32_768) > context_capacity_chars(8_192) > 0


def test_capacity_caps_a_preferred_size_that_does_not_fit():
    """The cap binds only when someone asks for a chunk larger than the window allows.

    Note it cannot bind on the default any more: a window small enough to afford under
    2,000 characters raises instead, so `min()` always returns the default in practice.
    The cap therefore exists for configured overrides, and is tested through one.
    """
    small_window = 4_096
    capacity = context_capacity_chars(small_window)
    assert capacity < 8_000
    assert chunk_size_for(small_window, preferred=8_000) == capacity


def test_default_chunk_size_is_small_on_measured_evidence():
    """2,000, not 'whatever the window holds'. See experiments/CHUNK_SIZE.md.

    Written docs: 4,000 chars recovered 31% of findable claims, 2,000 recovered 44%.
    Spoken transcript: 4,000 recovered 25%, 2,000 recovered 39% and was the best measured.
    """
    assert DEFAULT_CHUNK_CHARS == 2_000
    assert chunk_size_for(32_768) == 2_000


def test_preferred_chunk_size_is_overridable():
    assert chunk_size_for(32_768, preferred=1_500) == 1_500


def test_chunk_size_refuses_a_window_too_small_to_work():
    with pytest.raises(ValueError):
        chunk_size_for(2048)


def test_extractor_uses_the_small_default_not_the_context_window():
    """Regression guard: the whole document must not arrive in one call."""
    llm = ScriptedLLM(*['{"claims": []}'] * 20)
    text = "\n\n".join(f"paragraph {i} " + "w" * 400 for i in range(40))  # ~16 KB
    Extractor(llm=llm, model="m", num_ctx=32768, pack=make_pack()).extract(text, "s")
    assert len(llm.prompts) >= 4, "a 16 KB document should be split, not sent whole"


def test_short_text_is_one_chunk():
    assert split_text("a short note", 1000) == ["a short note"]


def test_long_text_is_split_and_nothing_is_lost():
    paragraphs = [f"paragraph number {i} " + "x" * 200 for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = split_text(text, 500)
    assert len(chunks) > 1
    joined = " ".join(chunks)
    for i in range(20):
        assert f"paragraph number {i}" in joined


def test_single_oversized_paragraph_is_hard_split():
    chunks = split_text("y" * 5000, 500)
    assert len(chunks) >= 10
    assert all(len(c) <= 500 for c in chunks)


# -- tolerant JSON parsing -----------------------------------------------------


def test_parses_clean_json():
    assert parse_claims_json('{"claims": [{"claim": "a"}]}') == [{"claim": "a"}]


def test_parses_fenced_json():
    raw = 'Sure!\n```json\n{"claims": [{"claim": "b"}]}\n```\nHope that helps.'
    assert parse_claims_json(raw) == [{"claim": "b"}]


def test_parses_bare_list():
    assert parse_claims_json('[{"claim": "c"}]') == [{"claim": "c"}]


def test_empty_output_is_empty_list_not_an_error():
    assert parse_claims_json("") == []
    assert parse_claims_json("I could not find any claims.") == []


# -- extraction ----------------------------------------------------------------


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []
        self.num_ctxs = []

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        self.prompts.append(prompt)
        self.num_ctxs.append(num_ctx)
        return self.responses.pop(0) if self.responses else '{"claims": []}'


def make_pack() -> Pack:
    return Pack(
        name="testpack",
        version="1",
        description="",
        schema={"claim": "the assertion"},
        extract_prompt="Find claims in:\n__TEXT__\nReturn {\"claims\": []} if none.",
    )


def test_extraction_produces_claims_with_stable_ids():
    llm = ScriptedLLM('{"claims": [{"claim": "quantisation costs accuracy", "kind": "limitation"}]}')
    extractor = Extractor(llm=llm, model="m", num_ctx=32768, pack=make_pack())
    claims = extractor.extract("some source text", "source-1")

    assert len(claims) == 1
    assert claims[0].text == "quantisation costs accuracy"
    assert claims[0].fields["kind"] == "limitation"

    llm2 = ScriptedLLM('{"claims": [{"claim": "quantisation costs accuracy", "kind": "limitation"}]}')
    again = Extractor(llm=llm2, model="m", num_ctx=32768, pack=make_pack()).extract(
        "some source text", "source-1"
    )
    assert again[0].id == claims[0].id


def test_extraction_passes_the_configured_context_window():
    llm = ScriptedLLM('{"claims": []}')
    Extractor(llm=llm, model="m", num_ctx=32768, pack=make_pack()).extract("text", "s")
    assert llm.num_ctxs == [32768]


def test_prompt_placeholder_survives_literal_json_braces():
    """The prompt contains literal braces; str.format() would raise KeyError on them."""
    llm = ScriptedLLM('{"claims": []}')
    Extractor(llm=llm, model="m", num_ctx=32768, pack=make_pack()).extract("MY TEXT", "s")
    assert "MY TEXT" in llm.prompts[0]
    assert '{"claims": []}' in llm.prompts[0]


def test_empty_extraction_is_not_an_error():
    llm = ScriptedLLM('{"claims": []}')
    claims = Extractor(llm=llm, model="m", num_ctx=32768, pack=make_pack()).extract("t", "s")
    assert claims == []


def test_duplicate_claims_within_a_source_are_collapsed():
    llm = ScriptedLLM(
        '{"claims": [{"claim": "same thing"}, {"claim": "same thing"}, {"claim": "other"}]}'
    )
    claims = Extractor(llm=llm, model="m", num_ctx=32768, pack=make_pack()).extract("t", "s")
    assert len(claims) == 2


# -- cost gate -----------------------------------------------------------------


def test_short_run_needs_no_acceptance():
    gate(Projection(unit_seconds=0.5, units=10), accepted=False)  # 5s, no exception


def test_long_run_is_refused_without_acceptance():
    with pytest.raises(RunRefused) as exc:
        gate(Projection(unit_seconds=5.0, units=1000), accepted=False)  # 83 minutes
    assert "83" in str(exc.value) or "1.4 hours" in str(exc.value)


def test_long_run_proceeds_once_accepted():
    gate(Projection(unit_seconds=5.0, units=1000), accepted=True)


def test_an_accepted_run_still_shows_its_projection(capsys):
    """Acceptance must not silence the number.

    `--accept-minutes 999999` used to start a 1,389-hour run without the user ever seeing
    a projection, while the documentation promised the tool shows the number and waits.
    A budget accepted sight-unseen is not informed consent.
    """
    gate(Projection(unit_seconds=5.0, units=1000), accepted=True)
    err = capsys.readouterr().err
    assert "projected run:" in err
    assert "83.3 minutes" in err  # 5000s; human() switches to hours above 5400s


def test_a_refused_run_also_shows_its_projection(capsys):
    with pytest.raises(RunRefused):
        gate(Projection(unit_seconds=5.0, units=1000), accepted=False)
    assert "projected run:" in capsys.readouterr().err


def test_a_short_run_stays_quiet(capsys):
    """A gate that fires on a twenty-second job trains people to ignore it."""
    gate(Projection(unit_seconds=0.5, units=10), accepted=False)
    assert capsys.readouterr().err == ""


def test_the_projection_goes_to_stderr_not_stdout(capsys):
    """A caller parsing stdout should not have to filter progress chatter."""
    gate(Projection(unit_seconds=5.0, units=1000), accepted=True)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_acceptance_must_cover_the_projection():
    projection = Projection(unit_seconds=6.0, units=1000)  # 100 minutes
    assert accepted_by_flag(120, projection) is True
    assert accepted_by_flag(30, projection) is False
    assert accepted_by_flag(None, projection) is False


def test_projection_reports_the_measurement_it_used():
    described = Projection(unit_seconds=2.5, units=400).describe()
    assert "2.50s" in described
    assert "400" in described


# -- projecting uneven work ----------------------------------------------------
#
# Found by running against a real corpus: 1057 files ranging from 24 bytes to 91 KB.
# Timing one file and multiplying by the file count projected 10.1 hours from a sample
# that happened to be large; a small file would have projected minutes. Neither is the
# truth, because the work scales with text volume, not with file count.


def test_volume_projection_ignores_file_count():
    """Same total bytes, wildly different file counts -> same projected time."""
    few_big = Projection(unit_seconds=1.0, units=10, sample_bytes=1000, total_bytes=100_000)
    many_small = Projection(unit_seconds=1.0, units=1000, sample_bytes=1000, total_bytes=100_000)
    assert few_big.total_seconds == pytest.approx(many_small.total_seconds)
    assert few_big.total_seconds == pytest.approx(100.0)  # 1000 bytes/s over 100 KB


def test_unrepresentative_sample_no_longer_dominates():
    """A sample 18x the median must not multiply the whole projection by 18."""
    # 1000 files, 5 KB each = 5 MB total. Sample happens to be a 90 KB monster taking 34s.
    projection = Projection(
        unit_seconds=34.0, units=1000, sample_bytes=90_000, total_bytes=5_000_000
    )
    naive_hours = 34.0 * 1000 / 3600
    assert naive_hours > 9  # what the old file-count estimator would have said
    assert projection.total_seconds / 3600 < 1  # what volume scaling actually says


def test_volume_projection_describes_a_throughput():
    described = Projection(
        unit_seconds=2.0, units=100, sample_bytes=10_240, total_bytes=1_024_000
    ).describe()
    assert "KB/s" in described
    assert "100 files" in described


def test_file_count_projection_still_used_when_sizes_are_unknown():
    projection = Projection(unit_seconds=3.0, units=10)
    assert not projection.scales_by_volume
    assert projection.total_seconds == pytest.approx(30.0)
