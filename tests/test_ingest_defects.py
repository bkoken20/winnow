"""Regressions found by cold review, on the default `ingest` path.

Both were guaranteed in the README as rules the tool "will not bend", both had tests, and
both tests exercised `index_note` while the default path is `ingest`. Testing the layer
beneath the real one is how a guarantee stays green while failing in use.
"""

import json
from pathlib import Path

from winnow.config import Config
from winnow.extract import Extractor
from winnow.models import NOVELTY_UNKNOWN
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class ManyClaimsLLM:
    """One claim per line, so a single transcript yields as many claims as it has lines."""

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


class RepeatedClaimLLM:
    """One assertion in three wordings -- what multi-pass extraction really produces.

    The variants differ in punctuation and case rather than vocabulary, because the offline
    hashing embedder used in tests compares token bags: it scores "use" against "usage" at
    0.86, below the 0.93 threshold, so a vocabulary variant would not exercise suppression
    at all. Distinct claim text (hence distinct ids), near-identical vectors.
    """

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        return json.dumps({"claims": [
            {"claim": "quantisation cuts memory use on consumer hardware"},
            {"claim": "quantisation cuts memory use on consumer hardware."},
            {"claim": "Quantisation cuts memory use on consumer hardware!"},
        ]})


def build(tmp_path, llm, **overrides) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        ingest_extra_passes=[],  # one pass; the defects are not about pass count
        **overrides,
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(llm=llm, model="fake", num_ctx=32768, pack=pipeline.pack)
    return pipeline


SUBJECTS = [
    "quantisation", "attention", "batching", "tokenisation", "caching", "scheduling",
    "embeddings", "retrieval", "sampling", "checkpointing", "sharding", "profiling",
    "compilation", "offloading", "prefetching", "distillation", "pruning", "routing",
    "streaming", "logging", "throttling", "warmup", "eviction", "paging", "fusion",
    "serialisation", "validation", "telemetry", "rebalancing", "prefixing",
    "collation", "annealing", "clipping", "masking", "pooling", "gating", "dropout",
    "layernorm", "beamsearch", "rescoring",
]


def _distinct_claim(i: int) -> str:
    """Claims that differ in VOCABULARY, not just in an index number.

    The offline hashing embedder compares token bags, so "assertion 3 on topic 3" and
    "assertion 4 on topic 4" score as near-identical and within-batch de-duplication
    collapses them. Real embeddings would keep them apart; the fixture has to.
    """
    return f"{SUBJECTS[i % len(SUBJECTS)]} shifts throughput by {i * 3 + 7} percent"


def _assert_fixture_is_actually_distinct(texts: list[str]) -> None:
    """Fail loudly if the test embedder cannot tell the fixture claims apart.

    The hashing embedder buckets tokens into 256 dimensions, so two unrelated words can
    collide and make two claims look identical -- collapsing them, and failing the test
    for a reason that has nothing to do with the behaviour under examination. Check the
    premise rather than letting it fail obscurely downstream.
    """
    from winnow.embed import HashingEmbedder, cosine_similarity

    embedder = HashingEmbedder()
    vectors = [embedder.embed(t) for t in texts]
    for a in range(len(vectors)):
        for b in range(a + 1, len(vectors)):
            similarity = cosine_similarity(vectors[a], vectors[b])
            assert similarity < 0.93, (
                f"fixture claims {a} and {b} collide in the test embedder "
                f"(similarity {similarity:.3f}): {texts[a]!r} vs {texts[b]!r}"
            )


def material(tmp_path, text: str) -> Path:
    folder = tmp_path / "talk"
    folder.mkdir(exist_ok=True)
    (folder / "transcript.txt").write_text(text, encoding="utf-8")
    return folder


# -- M2: a talk must not become its own evidence -------------------------------


def test_one_long_ingest_cannot_lift_itself_over_the_corpus_minimum(tmp_path):
    """Claims from THIS ingest must not count as the corpus that judges it.

    Coverage was read per claim from a corpus that the same ingest was filling, so a
    transcript with more claims than `min_corpus` started issuing real verdicts partway
    through -- judged against nothing but itself.
    """
    pipeline = build(tmp_path, ManyClaimsLLM())
    assert pipeline.pack.min_corpus == 25

    # Comfortably inside one chunk: a block straddling the 2,000-char boundary is hard-split
    # mid-line, and the fake extractor then reports the two halves as separate claims.
    lines = [_distinct_claim(i) for i in range(40)]
    _assert_fixture_is_actually_distinct(lines)
    text = "\n".join(lines)
    assert len(text) < 2_000  # one chunk: a straddling block is hard-split mid-line
    _, verdicts = pipeline.ingest(material(tmp_path, text))

    assert len(verdicts) == 40
    assert all(v.novelty == NOVELTY_UNKNOWN for v in verdicts), (
        "every claim must read `unknown`: the corpus was empty when this ingest began"
    )
    assert all(v.coverage.corpus_claims == 0 for v in verdicts), (
        "coverage must report the corpus as it was at the start of the ingest"
    )
    pipeline.close()


def test_a_talk_is_not_judged_against_itself(tmp_path):
    """Repeating a point in one talk must not make the repeat `known`."""
    pipeline = build(tmp_path, ManyClaimsLLM())
    # Seed a corpus so verdicts are real rather than `unknown`.
    notes = tmp_path / "notes"
    notes.mkdir()
    for i in range(30):
        (notes / f"n{i:02d}.md").write_text(f"unrelated corpus fact {i} concerning topic {i}",
                                            encoding="utf-8")
    pipeline.index_notes_folder(notes)

    # Two spellings of one point. Identical text collapses to a single claim inside the
    # extractor (same id), so the repeat must differ in punctuation to reach the judge at
    # all -- which is exactly the shape multi-pass extraction produces.
    text = "a speaker makes one particular point\na speaker makes one particular point."
    _, verdicts = pipeline.ingest(material(tmp_path, text))

    # One point, reported once. Previously the repeat was judged against the first
    # mention and came back `known`; now the corpus is frozen for the whole ingest, so
    # both would read the same -- and reporting one discovery twice is noise, so the
    # duplicate collapses instead.
    assert len(verdicts) == 1
    assert verdicts[0].novelty != "known", (
        "the point was judged against the same talk it came from"
    )
    pipeline.close()


# -- M3: duplicate suppression must apply where duplicates are produced --------


def test_ingest_does_not_store_near_duplicates(tmp_path):
    """Suppression ran on `index_note` only -- not on `ingest`, where multi-pass lives."""
    pipeline = build(tmp_path, RepeatedClaimLLM())
    pipeline.ingest(material(tmp_path, "anything"))

    assert pipeline.store.count_claims("ai_tooling") == 1, (
        "three wordings of one assertion should leave one claim in the corpus"
    )
    pipeline.close()


def test_one_assertion_is_reported_once_however_many_passes_found_it(tmp_path):
    """Three wordings of one point are one finding, not three.

    Multi-pass extraction reliably produces rewordings. With the corpus frozen for the
    whole ingest they all receive the same verdict, so reporting each would present one
    discovery as several.
    """
    pipeline = build(tmp_path, RepeatedClaimLLM())
    claims, verdicts = pipeline.ingest(material(tmp_path, "anything"))

    assert len(claims) == 1
    assert len(verdicts) == 1
    pipeline.close()


def test_a_claim_already_in_the_corpus_is_still_reported(tmp_path):
    """Collapsing applies WITHIN a batch only.

    A claim the corpus already holds must still be shown -- `known` is the tool's most
    informative verdict, and silently dropping it would hide the very thing a reader is
    asking about.
    """
    pipeline = build(tmp_path, RepeatedClaimLLM())
    pipeline.ingest(material(tmp_path, "first"))          # corpus now holds the assertion
    before = pipeline.store.count_claims("ai_tooling")

    second = tmp_path / "talk2"
    second.mkdir()
    (second / "transcript.txt").write_text("anything", encoding="utf-8")
    _, verdicts = pipeline.ingest(second)

    assert len(verdicts) == 1, "the repeat must still be reported"
    assert pipeline.store.count_claims("ai_tooling") == before, "but not stored again"
    pipeline.close()


def test_suppression_is_configurable_on_the_ingest_path_too(tmp_path):
    pipeline = build(tmp_path, RepeatedClaimLLM(), duplicate_threshold=0.0)
    pipeline.ingest(material(tmp_path, "anything"))
    assert pipeline.store.count_claims("ai_tooling") == 3
    pipeline.close()
