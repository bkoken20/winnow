"""The verdict layer's two non-negotiables: coverage honesty and judge stamping."""

import pytest

from winnow.embed import HashingEmbedder
from winnow.judge import Judge, JudgeConfig, novelty_from_similarity
from winnow.models import (
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNKNOWN,
    NOVELTY_VALUES,
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


def test_the_tier_one_stamp_records_every_field(tmp_path):
    """Every field, not a sample of them.

    Found by mutation testing: flipping the tier check on the judge_location line alone
    survived the entire suite, so a cloud-judged verdict could record no location at all.
    That is the field a reader would use to work out whether their claim text was sent
    anywhere.
    """
    class FakeLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return '{"novelty": "known", "specificity": "concrete", '\
                   '"evidence": "measurement", "flags": [], "rationale": "seen before"}'

    store = Store(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    config = JudgeConfig(
        pack=PACK, min_corpus=1, judge_model="big-model",
        judge_location="cloud", pack_version="7.7",
    )
    judge = Judge(store, embedder, config, llm=FakeLLM())
    fill_corpus(store, embedder, 3)

    stamp = judge.judge_claim(make_claim("a claim to judge")).judge

    assert stamp.tier == 1
    assert stamp.embed_model == embedder.name
    assert stamp.embed_backend == embedder.backend
    assert stamp.judge_model == "big-model"
    assert stamp.judge_location == "cloud", (
        "a cloud-judged verdict must say so; this is the field that records whether the "
        "claim text left the machine"
    )
    assert stamp.prompt_version != ""
    assert stamp.pack_version == "7.7"


def test_the_tier_zero_stamp_claims_no_judge_it_did_not_use(tmp_path):
    """The mirror. A tier-0 verdict must not carry a judge model, location or prompt."""
    judge, store, embedder = build_judge(tmp_path, min_corpus=1)
    fill_corpus(store, embedder, 3)

    stamp = judge.judge_claim(make_claim("a claim to judge")).judge

    assert stamp.tier == 0
    assert stamp.judge_model == ""
    assert stamp.judge_location == "", (
        "no language model was consulted, so recording a location would misdescribe "
        "where the verdict came from"
    )
    assert stamp.prompt_version == ""
    assert stamp.embed_model == embedder.name


def test_the_readme_lists_every_stamped_field(tmp_path):
    """The promise enumerates the fields, so the enumeration has to be complete.

    It named five of seven: `tier` and `judge_location` were missing, which is how a
    guarantee quietly stops covering the field nobody listed.
    """
    import dataclasses
    from pathlib import Path

    import re

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    # Collapse wrapping: the promise spans lines, so a phrase can be split across one.
    collapsed = re.sub(r"\s+", " ", readme.split("Every verdict records what judged it")[1])
    # The ENUMERATION is the first sentence, and only that. Reading a wider window let the
    # paragraph that explains a field stand in for the list that is supposed to name it:
    # deleting the field from the list left this test green, because the explanation below
    # still mentioned it.
    promise = collapsed.split(". ")[0]

    english = {
        "tier": "tier",
        "embed_model": "embedding model",
        "embed_backend": "backend",
        "judge_model": "judge model",
        "judge_location": "judge location",
        "prompt_version": "prompt version",
        "pack_version": "pack version",
        "stayed_on_this_machine": "whether the material stayed on this machine",
    }
    fields = [f.name for f in dataclasses.fields(JudgeStamp)]
    assert set(fields) == set(english), f"JudgeStamp gained or lost a field: {fields}"

    missing = [english[f] for f in fields if english[f] not in promise.lower()]
    assert not missing, (
        f"the README promises the stamp records what judged a verdict but does not "
        f"list: {missing}"
    )


@pytest.mark.parametrize(
    "response",
    [
        '["new", "concrete"]',       # a JSON array
        '"new"',                     # a bare JSON string
        "42",                        # a bare number
        "null",                      # valid JSON, no content
        "true",
    ],
)
def test_valid_json_that_is_not_an_object_falls_back(tmp_path, response):
    """The fallback exists for garbage; this garbage happens to parse.

    json.JSONDecodeError was the only thing caught, so a judge answering with an array or a
    bare string reached `parsed.get` and raised AttributeError -- uncaught by the CLI, so a
    traceback after all the extraction work was already done.
    """
    class OddLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return response

    judge, store, embedder = build_judge(
        tmp_path, min_corpus=1, llm=OddLLM(), judge_model="odd"
    )
    fill_corpus(store, embedder, 3)

    verdict = judge.judge_claim(make_claim("a claim to judge"))

    assert verdict.novelty in NOVELTY_VALUES
    assert verdict.judge.tier == 1, "it was still a tier-1 attempt and must be stamped as one"
    assert "fell back" in verdict.rationale or verdict.rationale


def test_flags_that_are_not_a_list_do_not_become_one_flag_per_character(tmp_path):
    """`list("scam")` is ['s','c','a','m'], which would be four flags on every verdict."""
    class StringFlagsLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return ('{"novelty": "new", "specificity": "concrete", "evidence": '
                    '"asserted", "flags": "scam", "rationale": "looks promotional"}')

    judge, store, embedder = build_judge(
        tmp_path, min_corpus=1, llm=StringFlagsLLM(), judge_model="odd"
    )
    fill_corpus(store, embedder, 3)

    verdict = judge.judge_claim(make_claim("a claim to judge"))

    assert verdict.flags == ["scam"], f"got {verdict.flags}"


def test_tier_one_falls_back_when_judge_returns_garbage(tmp_path):
    class BrokenLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return "I'm afraid I can't do that."

    judge, store, embedder = build_judge(
        tmp_path, min_corpus=1, llm=BrokenLLM(), judge_model="broken"
    )
    fill_corpus(store, embedder, 3)
    verdict = judge.judge_claim(make_claim("a claim"))

    # Assert the behaviour, not the adjective. This pinned the word "unparseable", which
    # stopped being the whole story once output that PARSES but is the wrong shape had to
    # take the same path.
    assert "fell back" in verdict.rationale
    assert verdict.novelty in NOVELTY_VALUES
    assert verdict.judge.tier == 1, "it was a tier-1 attempt and must be stamped as one"


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
