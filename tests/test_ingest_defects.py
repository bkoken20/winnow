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
    text = "\n".join(f"assertion {i} on topic {i}" for i in range(40))
    assert len(text) < 1_500
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

    assert len(verdicts) == 2
    assert verdicts[1].novelty != "known", (
        "the second mention was judged against the first, which arrived in the same talk"
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


def test_ingest_still_reports_a_verdict_for_every_extracted_claim(tmp_path):
    """Suppression governs what is STORED, never what the user is told.

    A reader who asks about a talk should see a verdict per claim found in it, even when
    the corpus declines to keep a reworded duplicate.
    """
    pipeline = build(tmp_path, RepeatedClaimLLM())
    claims, verdicts = pipeline.ingest(material(tmp_path, "anything"))

    assert len(claims) == 3
    assert len(verdicts) == 3
    pipeline.close()


def test_suppression_is_configurable_on_the_ingest_path_too(tmp_path):
    pipeline = build(tmp_path, RepeatedClaimLLM(), duplicate_threshold=0.0)
    pipeline.ingest(material(tmp_path, "anything"))
    assert pipeline.store.count_claims("ai_tooling") == 3
    pipeline.close()
