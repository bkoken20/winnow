"""The verdict layer's two non-negotiables: coverage honesty and judge stamping."""

import pytest

from winnow.embed import HashingEmbedder
from winnow.judge import Judge, JudgeConfig, novelty_from_similarity
from winnow.models import (
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNKNOWN,
    NOVELTY_VARIANT,
    Claim,
    Coverage,
    JudgeStamp,
)
from winnow.store import Store

PACK = "testpack"


def make_claim(text: str, cid: str = "") -> Claim:
    return Claim(id=cid or text[:16], pack=PACK, source_id="src", text=text)


def fill_corpus(store: Store, embedder, count: int) -> None:
    from winnow.models import Source

    store.add_source(Source(id="src", pack=PACK, kind="note", path="/x"))
    for i in range(count):
        text = f"corpus claim number {i} about an unrelated subject"
        claim = make_claim(text, cid=f"c{i}")
        store.add_claim(claim, embedder.embed(text), embedder.name)


def build_judge(tmp_path, min_corpus=25, llm=None, judge_model=""):
    store = Store(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    config = JudgeConfig(pack=PACK, min_corpus=min_corpus, judge_model=judge_model)
    return Judge(store, embedder, config, llm=llm), store, embedder


# -- coverage honesty ----------------------------------------------------------


def test_thin_corpus_yields_unknown_not_new(tmp_path):
    """A blind spot must never be reported as a discovery."""
    judge, store, embedder = build_judge(tmp_path, min_corpus=25)
    fill_corpus(store, embedder, 3)  # well below the minimum

    verdict = judge.judge_claim(make_claim("something nobody has ever said before"))

    assert verdict.novelty == NOVELTY_UNKNOWN
    assert not verdict.coverage.sufficient
    assert "3 claims" in verdict.rationale


def test_empty_corpus_yields_unknown(tmp_path):
    judge, _, _ = build_judge(tmp_path, min_corpus=25)
    verdict = judge.judge_claim(make_claim("the very first claim ever seen"))
    assert verdict.novelty == NOVELTY_UNKNOWN
    assert verdict.coverage.corpus_claims == 0


def test_sufficient_corpus_allows_a_real_verdict(tmp_path):
    judge, store, embedder = build_judge(tmp_path, min_corpus=5)
    fill_corpus(store, embedder, 10)
    verdict = judge.judge_claim(make_claim("a completely different assertion entirely"))
    assert verdict.novelty in (NOVELTY_NEW, NOVELTY_VARIANT, NOVELTY_KNOWN)
    assert verdict.coverage.sufficient


def test_verdict_always_carries_its_evidence_base(tmp_path):
    judge, store, embedder = build_judge(tmp_path, min_corpus=5)
    fill_corpus(store, embedder, 7)
    verdict = judge.judge_claim(make_claim("anything at all"))
    assert verdict.coverage.corpus_claims == 7
    assert verdict.coverage.min_for_verdict == 5


def test_restatement_is_recognised_as_known(tmp_path):
    judge, store, embedder = build_judge(tmp_path, min_corpus=2)
    fill_corpus(store, embedder, 5)
    # Identical text to an existing corpus claim, under a different id.
    duplicate = "corpus claim number 2 about an unrelated subject"
    verdict = judge.judge_claim(make_claim(duplicate, cid="different-id"))
    assert verdict.novelty == NOVELTY_KNOWN
    assert verdict.similarity > 0.99


# -- stamping ------------------------------------------------------------------


def test_every_verdict_is_stamped_with_its_judge(tmp_path):
    judge, store, embedder = build_judge(tmp_path, min_corpus=1)
    fill_corpus(store, embedder, 3)
    verdict = judge.judge_claim(make_claim("some claim"))
    assert verdict.judge.tier == 0
    assert verdict.judge.embed_model == embedder.name
    assert verdict.judge.embed_backend == "hashing"


def test_hashing_backend_is_marked_untrustworthy(tmp_path):
    """Verdicts computed with the offline test embedder must be identifiable as such."""
    judge, store, embedder = build_judge(tmp_path, min_corpus=1)
    fill_corpus(store, embedder, 3)
    verdict = judge.judge_claim(make_claim("some claim"))
    assert verdict.judge.is_trustworthy() is False


def test_real_backend_is_trustworthy():
    stamp = JudgeStamp(tier=0, embed_model="nomic-embed-text", embed_backend="ollama")
    assert stamp.is_trustworthy() is True


def test_tier_one_records_the_judge_model(tmp_path):
    class FakeLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return '{"novelty": "known", "specificity": "concrete", '\
                   '"evidence": "measurement", "flags": [], "rationale": "seen before"}'

    judge, store, embedder = build_judge(
        tmp_path, min_corpus=1, llm=FakeLLM(), judge_model="big-model"
    )
    fill_corpus(store, embedder, 3)
    verdict = judge.judge_claim(make_claim("a claim to judge"))

    assert judge.tier == 1
    assert verdict.judge.judge_model == "big-model"
    assert verdict.judge.prompt_version != ""
    assert verdict.novelty == NOVELTY_KNOWN
    assert verdict.evidence == "measurement"


def test_tier_one_falls_back_when_judge_returns_garbage(tmp_path):
    class BrokenLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return "I'm afraid I can't do that."

    judge, store, embedder = build_judge(
        tmp_path, min_corpus=1, llm=BrokenLLM(), judge_model="broken"
    )
    fill_corpus(store, embedder, 3)
    verdict = judge.judge_claim(make_claim("a claim"))
    assert "unparseable" in verdict.rationale


# -- thresholds ----------------------------------------------------------------


@pytest.mark.parametrize(
    "similarity,expected",
    [(0.99, NOVELTY_KNOWN), (0.90, NOVELTY_KNOWN), (0.80, NOVELTY_VARIANT), (0.10, NOVELTY_NEW)],
)
def test_similarity_maps_to_novelty(similarity, expected):
    assert novelty_from_similarity(similarity, JudgeConfig(pack=PACK)) == expected


def test_coverage_sufficiency_is_a_simple_threshold():
    assert Coverage(corpus_claims=25, min_for_verdict=25).sufficient
    assert not Coverage(corpus_claims=24, min_for_verdict=25).sufficient
