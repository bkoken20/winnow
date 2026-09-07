"""Multi-pass extraction, and the near-duplicate suppression it makes necessary.

Measured in experiments/TWO_PASS.md: a second extraction pass at a *different* small chunk
size raises coverage by 25-32 points, because different chunk boundaries put different
sentences beside each other and each pass surfaces different claims. A whole-document second
pass, which was the original hypothesis, adds only ~3 points and loses outright to simply
using a smaller single pass at the same cost.

Running two passes over one text produces genuine rewordings of the same assertion, so the
corpus suppresses near-duplicates on insert. Without that, a corpus fills with echoes of
itself and later novelty verdicts read `known` for the wrong reason.
"""

import json
from pathlib import Path

from winnow.config import Config
from winnow.extract import Extractor
from winnow.packs import Pack
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


def make_pack() -> Pack:
    return Pack(
        name="testpack",
        version="1",
        description="",
        schema={"claim": "the assertion"},
        extract_prompt="Find claims in:\n__TEXT__\n",
    )


class RecordingLLM:
    def __init__(self):
        self.chunks = []

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        self.chunks.append(prompt.split("Find claims in:\n")[-1])
        return json.dumps({"claims": []})


# -- pass plumbing -------------------------------------------------------------


def test_single_pass_by_default():
    extractor = Extractor(llm=RecordingLLM(), model="m", num_ctx=32768, pack=make_pack())
    assert extractor.passes == [extractor.chunk_chars]


def test_extra_pass_re_reads_the_text_at_a_different_size():
    llm = RecordingLLM()
    text = "\n\n".join(f"paragraph {i} " + "z" * 300 for i in range(30))  # ~9 KB
    extractor = Extractor(
        llm=llm, model="m", num_ctx=32768, pack=make_pack(),
        chunk_chars=2_000, extra_passes=(1_000,),
    )
    extractor.extract(text, "s")

    one_pass = RecordingLLM()
    Extractor(
        llm=one_pass, model="m", num_ctx=32768, pack=make_pack(), chunk_chars=2_000
    ).extract(text, "s")

    assert len(llm.chunks) > len(one_pass.chunks)
    # The whole text is covered twice over, not merely split more finely once.
    assert sum(len(c) for c in llm.chunks) > 1.8 * sum(len(c) for c in one_pass.chunks)


def test_boundaries_actually_differ_between_passes():
    """If both passes cut at the same points, the second pass buys nothing."""
    llm = RecordingLLM()
    text = "\n\n".join(f"paragraph {i} " + "z" * 300 for i in range(30))
    Extractor(
        llm=llm, model="m", num_ctx=32768, pack=make_pack(),
        chunk_chars=2_000, extra_passes=(1_000,),
    ).extract(text, "s")
    assert len(set(llm.chunks)) == len(llm.chunks), "passes produced identical chunks"


# -- near-duplicate suppression ------------------------------------------------


class FixedClaimsLLM:
    """Returns the same assertion in two wordings, plus one distinct one."""

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        return json.dumps(
            {
                "claims": [
                    {"claim": "quantisation cuts memory use on consumer hardware"},
                    {"claim": "quantisation cuts memory use on consumer hardware."},
                    {"claim": "batching raises throughput on server hardware"},
                ]
            }
        )


def build(tmp_path, **overrides) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        **overrides,
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(
        llm=FixedClaimsLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    return pipeline


def test_near_duplicates_are_not_stored_twice(tmp_path):
    pipeline = build(tmp_path)
    note = tmp_path / "n.md"
    note.write_text("anything", encoding="utf-8")

    stored = pipeline.index_note(note)

    assert stored == 2, "the two wordings of one assertion should collapse to one"
    assert pipeline.store.count_claims("ai_tooling") == 2
    pipeline.close()


def test_suppression_can_be_switched_off(tmp_path):
    pipeline = build(tmp_path, duplicate_threshold=0.0)
    note = tmp_path / "n.md"
    note.write_text("anything", encoding="utf-8")

    assert pipeline.index_note(note) == 3
    pipeline.close()


def test_a_second_note_repeating_the_first_adds_nothing(tmp_path):
    pipeline = build(tmp_path)
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text("anything", encoding="utf-8")
        pipeline.index_note(tmp_path / name)

    assert pipeline.store.count_claims("ai_tooling") == 2
    pipeline.close()


def test_distinct_claims_are_all_kept(tmp_path):
    class DistinctLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return json.dumps(
                {
                    "claims": [
                        {"claim": "quantisation cuts memory use on consumer hardware"},
                        {"claim": "retrieval quality dominates model size for document search"},
                        {"claim": "speculative decoding helps most at batch size one"},
                    ]
                }
            )

    pipeline = build(tmp_path)
    pipeline.extractor = Extractor(
        llm=DistinctLLM(), model="fake", num_ctx=32768, pack=pipeline.pack
    )
    note = tmp_path / "n.md"
    note.write_text("anything", encoding="utf-8")

    assert pipeline.index_note(note) == 3
    pipeline.close()


# -- the cost asymmetry --------------------------------------------------------


def test_ingest_is_thorough_by_default_and_indexing_is_not(tmp_path):
    """Judging one item costs seconds; indexing a corpus costs hours.

    So the second pass is on for ingest and off for index, by default.
    """
    config = Config()
    assert config.ingest_extra_passes, "ingest should read the material more than once"
    assert config.index_extra_passes == [], "indexing should stay single-pass by default"

    pipeline = build(tmp_path)
    assert pipeline.extractor.extra_passes == ()  # index path
    pipeline.close()


def test_ingest_uses_every_configured_pass(tmp_path):
    pipeline = build(tmp_path)
    recording = RecordingLLM()
    pipeline.extractor = Extractor(
        llm=recording, model="fake", num_ctx=32768, pack=make_pack(), chunk_chars=2_000
    )

    material = tmp_path / "talk"
    material.mkdir()
    (material / "transcript.txt").write_text(
        "\n\n".join(f"paragraph {i} " + "z" * 300 for i in range(30)), encoding="utf-8"
    )
    pipeline.ingest(material)

    # Three passes by default, so the text is read three times over.
    total = sum(len(c) for c in recording.chunks)
    source = (material / "transcript.txt").read_text(encoding="utf-8")
    assert total > 2.5 * len(source), "ingest should have read the text about three times"
    pipeline.close()
