"""The cost projection must account for de-duplication scanning.

Each new claim is compared against every claim already stored, so scan cost per claim grows
linearly with the corpus and the run's total scan cost grows quadratically. The projection
measured only the first file -- against a corpus at its smallest -- and therefore
under-reported precisely the large runs the gate exists to protect against. Measured: at
5,000 claims a real run took 38s against a projection of 9s.

Validated against real runs at three corpus sizes (0 / 2,000 / 5,000 claims): the projection
now lands within 0.97x-1.19x of actual.
"""

import json
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.cost import Projection
from winnow.extract import Extractor
from winnow.models import Claim, Source
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


# -- the arithmetic ------------------------------------------------------------


def test_no_scan_data_means_no_dedupe_term():
    """An empty corpus has nothing to scan; the projection must not invent a cost."""
    projection = Projection(unit_seconds=2.0, units=10, sample_bytes=100, total_bytes=1000)
    assert projection.dedupe_seconds == 0.0
    assert projection.total_seconds == projection.extraction_seconds


def test_dedupe_cost_grows_with_the_number_of_new_claims():
    """Quadratic, not linear: claim i is compared against start + i existing claims."""
    small = Projection(
        unit_seconds=1.0, units=1, scan_seconds_per_claim=1e-5,
        corpus_claims_at_start=0, expected_new_claims=1_000,
    )
    double = Projection(
        unit_seconds=1.0, units=1, scan_seconds_per_claim=1e-5,
        corpus_claims_at_start=0, expected_new_claims=2_000,
    )
    ratio = double.dedupe_seconds / small.dedupe_seconds
    assert 3.5 < ratio < 4.5, f"doubling the claims should roughly quadruple scanning, got {ratio:.1f}x"


def test_dedupe_cost_grows_with_the_existing_corpus():
    """Adding to a big corpus costs more than the same work on an empty one."""
    fresh = Projection(
        unit_seconds=1.0, units=1, scan_seconds_per_claim=1e-5,
        corpus_claims_at_start=0, expected_new_claims=1_000,
    )
    established = Projection(
        unit_seconds=1.0, units=1, scan_seconds_per_claim=1e-5,
        corpus_claims_at_start=50_000, expected_new_claims=1_000,
    )
    assert established.dedupe_seconds > 50 * fresh.dedupe_seconds


def test_the_total_is_extraction_plus_scanning():
    projection = Projection(
        unit_seconds=1.0, units=10, sample_bytes=1000, total_bytes=10_000,
        scan_seconds_per_claim=1e-4, corpus_claims_at_start=100, expected_new_claims=100,
    )
    assert projection.total_seconds == (
        projection.extraction_seconds + projection.dedupe_seconds
    )
    assert projection.dedupe_seconds > 0


def test_the_description_says_scanning_is_included():
    """A number the user cannot account for is a number they will not trust."""
    described = Projection(
        unit_seconds=1.0, units=10, sample_bytes=1000, total_bytes=10_000,
        scan_seconds_per_claim=1e-4, corpus_claims_at_start=500, expected_new_claims=500,
    ).describe()
    assert "de-duplication" in described
    assert "500" in described


# -- the double-count regression -----------------------------------------------


class OneClaimLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps({"claims": [{"claim": body[:70]}]})


def build(tmp_path, seeded: int = 0) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        packs_root=str(PACKS_ROOT),
        embed_backend="hashing",
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(
        llm=OneClaimLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    if seeded:
        pipeline.store.add_source(
            Source(id="seed", pack="ai_tooling", kind="note", path="/s")
        )
        embedder = pipeline.judge.embedder
        for i in range(seeded):
            text = f"seeded assertion {i} concerning subject {i % 89} under load"
            pipeline.store.add_claim(
                Claim(id=f"s{i}", pack="ai_tooling", source_id="seed", text=text),
                embedder.embed(text),
                embedder.name,
            )
    return pipeline


def notes_folder(tmp_path, count: int) -> Path:
    folder = tmp_path / "notes"
    folder.mkdir(exist_ok=True)
    for i in range(count):
        (folder / f"f{i:03d}.md").write_text(
            f"distinct finding {i} regarding component {i} at scale", encoding="utf-8"
        )
    return folder


def test_the_extraction_term_excludes_the_sample_s_own_scanning(tmp_path, monkeypatch):
    """The measured unit time already contains the sample's de-duplication scan.

    Projecting scanning on top of it counted the same work twice and turned a real
    56-second run into a 125-second projection. A gate that cries wolf is ignored just as
    surely as one that stays silent.
    """
    pipeline = build(tmp_path, seeded=200)

    # A deliberately huge scan cost: if it is not subtracted from the extraction term,
    # the extraction term inflates with it.
    monkeypatch.setattr(pipeline.store, "measure_scan_cost", lambda *a, **k: 1e-3)

    result = pipeline.index_notes_folder(notes_folder(tmp_path, 5), accept_minutes=99999)
    projection = result["projection"]

    # 200 stored claims x 1 claim in the sample x 1e-3 = 0.2s of the sample's measured
    # time was scanning, and must not also appear in the projected dedupe term.
    assert projection.scan_seconds_per_claim == 1e-3
    assert projection.corpus_claims_at_start == 200
    assert projection.measured_unit_seconds > 0, "the raw measurement must be recorded"
    assert projection.unit_seconds < projection.measured_unit_seconds, (
        "the sample's own scan time must be subtracted from the extraction term, or the "
        "same work is counted twice"
    )
    expected_scan = 1e-3 * 200 * 1
    assert projection.unit_seconds == pytest.approx(
        max(projection.measured_unit_seconds - expected_scan, 1e-6), abs=1e-6
    )
    assert projection.dedupe_seconds > 0
    pipeline.close()


def test_scan_cost_is_actually_measured_against_a_real_corpus(tmp_path):
    """Guard the measurement itself, not just what is done with it.

    A `measure_scan_cost` that always returned zero left every projection unchanged and
    every other test in this file still passing.
    """
    pipeline = build(tmp_path, seeded=300)
    vector = pipeline.judge.embedder.embed("a probe claim")

    cost = pipeline.store.measure_scan_cost("ai_tooling", vector)
    assert cost > 0, "a non-empty corpus must report a real per-claim scan cost"

    empty = pipeline.store.measure_scan_cost("no_such_pack", vector)
    assert empty == 0.0, "an empty corpus has nothing to scan"
    pipeline.close()


def test_the_projection_reports_the_corpus_it_started_from(tmp_path):
    pipeline = build(tmp_path, seeded=50)
    result = pipeline.index_notes_folder(notes_folder(tmp_path, 3), accept_minutes=99999)
    assert result["projection"].corpus_claims_at_start == 50
    assert result["projection"].expected_new_claims == 3
    pipeline.close()


def test_an_empty_corpus_still_projects_without_scan_cost(tmp_path):
    pipeline = build(tmp_path, seeded=0)
    result = pipeline.index_notes_folder(notes_folder(tmp_path, 3), accept_minutes=99999)
    assert result["projection"].scan_seconds_per_claim == 0.0
    assert result["projection"].dedupe_seconds == 0.0
    pipeline.close()
