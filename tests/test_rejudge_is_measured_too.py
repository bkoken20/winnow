"""`rejudge` with a judge configured is one model call per claim, and nothing measured it.

`index` measures one file, projects the run, shows the number and refuses until you accept a
budget. `rejudge` walks every claim in the pack and calls `judge_claim` on each. At tier 0
that is embeddings only and genuinely cheap, which is what its docstring says:

    "Re-judging is cheap with embeddings, so a stale verdict is a choice rather than a
     constraint."

At tier 1 it is not. Set `judge_model` and every claim becomes an LLM call: on the 383-claim
corpus this repository was developed against, 383 of them, with no projection, no gate and no
announcement — the same shape of run `index` refuses to start without asking.

The docstring is half of the defect. It describes tier 0 and is read as describing the
command.

Reported by an external review.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from winnow.config import Config
from winnow.cost import RunRefused
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


class SlowJudgeLLM:
    """A judge that takes real time, because that is the whole point of the gate."""

    def __init__(self, seconds: float = 0.05):
        self.seconds = seconds
        self.calls = 0

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        self.calls += 1
        time.sleep(self.seconds)
        return json.dumps({"novelty": "known", "rationale": "seen before"})


# Distinct subjects, because near-identical lines are de-duplicated on the way in and the
# count would not be the count. Above the pack's `min_corpus` of 25, because below it
# `judge_claim` returns `unknown` without calling the judge at all -- a tier-1 rejudge over a
# thin corpus makes no model calls, so it cannot measure the cost this gate exists for.
SUBJECTS = [
    "quantisation", "attention", "batching", "tokenisation", "caching", "scheduling",
    "speculative decoding", "rotary embeddings", "flash attention", "paged attention",
    "grouped query attention", "mixture of experts", "prefix caching", "continuous batching",
    "tensor parallelism", "pipeline parallelism", "activation checkpointing", "LoRA",
    "QLoRA", "distillation", "pruning", "sparsity", "beam search", "nucleus sampling",
    "temperature", "repetition penalty", "context extension", "sliding windows",
    "retrieval augmentation", "reranking", "chunk overlap", "embedding dimensionality",
]


def _corpus(tmp_path, claims: int = 32) -> Path:
    """A corpus above `min_corpus`, built at tier 0."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text(
        "\n".join(
            f"{SUBJECTS[i % len(SUBJECTS)]} changes throughput by roughly {i + 3} percent "
            f"on consumer hardware"
            for i in range(claims)
        ),
        encoding="utf-8",
    )

    corpus = tmp_path / "winnow.db"
    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(corpus),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
            index_extra_passes=[],
        )
    )
    pipeline.extractor.llm = LineClaimsLLM()
    try:
        pipeline.index_notes_folder(notes, accept_minutes=600)
    finally:
        pipeline.close()
    return corpus


def _stored_claims(corpus: Path) -> int:
    """Read the count rather than assume it: extraction de-duplicates on the way in."""
    from winnow.store import Store

    store = Store.open_readonly(str(corpus))
    try:
        return store.count_claims("ai_tooling")
    finally:
        store.close()


def _tier_one(corpus: Path, judge_llm) -> Pipeline:
    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(corpus),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
            judge_model="qwen2.5:14b-instruct",
        )
    )
    pipeline.judge.llm = judge_llm
    return pipeline


def test_a_tier_one_rejudge_is_projected(tmp_path, capsys):
    corpus = _corpus(tmp_path)
    capsys.readouterr()

    pipeline = _tier_one(corpus, SlowJudgeLLM())
    try:
        result = pipeline.rejudge(accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    assert result.projection is not None, "a run of model calls started unmeasured"
    assert result.projection.units > 1, "the projection must cover every claim"
    expected = 0.05 * _stored_claims(corpus)
    assert result.projection.total_seconds > expected / 2, (
        f"{_stored_claims(corpus)} model calls at 0.05 s each cannot take "
        f"{result.projection.total_seconds:.4f} s"
    )


def test_a_tier_one_rejudge_is_refused_without_a_budget(tmp_path, capsys, monkeypatch):
    """The gate returns silently below 120 s, so reaching it means lowering the threshold."""
    from winnow import cost, pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "gate",
        lambda projection, accepted: cost.gate(projection, accepted, threshold_seconds=0.2),
    )

    corpus = _corpus(tmp_path)
    capsys.readouterr()

    pipeline = _tier_one(corpus, SlowJudgeLLM())
    try:
        with pytest.raises(RunRefused) as refused:
            pipeline.rejudge(accept_minutes=None)
    finally:
        pipeline.close()
    said = "".join(capsys.readouterr())

    assert "projected run:" in said, f"the number was never shown: {said!r}"
    assert "accept-minutes" in str(refused.value)


def test_a_tier_zero_rejudge_is_not_gated(tmp_path, capsys):
    """Embeddings only. A gate on a run that takes a second trains people to click past it."""
    corpus = _corpus(tmp_path)
    capsys.readouterr()

    pipeline = Pipeline.build(
        Config(
            pack="ai_tooling",
            corpus_path=str(corpus),
            embed_backend="hashing",
            packs_root=str(PACKS_ROOT),
        )
    )
    try:
        result = pipeline.rejudge()
    finally:
        pipeline.close()
    capsys.readouterr()

    assert result.projection is None, "tier 0 needs no budget and should not ask for one"
    assert len(result.verdicts) == _stored_claims(corpus)


def test_the_measured_claim_is_judged_once(tmp_path, capsys):
    """The sample is real work, so it must be kept rather than redone -- or double-counted."""
    corpus = _corpus(tmp_path)
    capsys.readouterr()

    judge_llm = SlowJudgeLLM(seconds=0.0)
    pipeline = _tier_one(corpus, judge_llm)
    try:
        result = pipeline.rejudge(accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    stored = _stored_claims(corpus)
    assert len(result.verdicts) == stored, "every claim gets exactly one verdict"
    assert judge_llm.calls == stored, (
        f"the sampled claim was judged twice: {judge_llm.calls} calls for {stored} claims"
    )


def test_an_empty_corpus_needs_no_projection(tmp_path, capsys):
    corpus = tmp_path / "winnow.db"
    from winnow.store import Store

    Store(str(corpus)).close()

    pipeline = _tier_one(corpus, SlowJudgeLLM())
    try:
        result = pipeline.rejudge(accept_minutes=600)
    finally:
        pipeline.close()
    capsys.readouterr()

    assert result.verdicts == []
    assert result.projection is None


def _verdict_count(corpus: Path) -> int:
    from winnow.store import Store

    store = Store.open_readonly(str(corpus))
    try:
        return len(store.latest_verdicts("ai_tooling", limit=10_000))
    finally:
        store.close()


def test_a_refused_rejudge_changes_nothing(tmp_path, capsys, monkeypatch):
    """The same guarantee `index` makes, which nothing held for this command.

    The measured claim is real work and its verdict is real, but it must not be stored
    until the gate has passed -- otherwise a refused run has already modified the corpus it
    refused to process, and the retry starts from a different place than the one the user
    was shown a number for.
    """
    from winnow import cost, pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "gate",
        lambda projection, accepted: cost.gate(projection, accepted, threshold_seconds=0.2),
    )

    corpus = _corpus(tmp_path)
    capsys.readouterr()
    before = (_verdict_count(corpus), corpus.read_bytes())

    pipeline = _tier_one(corpus, SlowJudgeLLM())
    try:
        with pytest.raises(RunRefused):
            pipeline.rejudge(accept_minutes=None)
    finally:
        pipeline.close()
    capsys.readouterr()

    after = (_verdict_count(corpus), corpus.read_bytes())
    assert after[0] == before[0], "a refused run wrote a verdict"
    assert after[1] == before[1], "a refused run modified the corpus file"


def test_the_budget_on_the_command_line_reaches_the_gate(tmp_path, capsys, monkeypatch):
    """A flag that is parsed and then dropped is worse than no flag at all.

    The refusal message tells the user to re-run with `--accept-minutes N`. If the command
    accepts that and does not pass it on, the advice sends them in a circle.
    """
    from winnow import cli, cost, pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module,
        "gate",
        lambda projection, accepted: cost.gate(projection, accepted, threshold_seconds=0.2),
    )

    corpus = _corpus(tmp_path)
    capsys.readouterr()

    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps(
            {
                "pack": "ai_tooling",
                "corpus_path": str(corpus),
                "embed_backend": "hashing",
                "packs_root": str(PACKS_ROOT),
                "judge_model": "qwen2.5:14b-instruct",
            }
        ),
        encoding="utf-8",
    )

    real_build = Pipeline.build

    def build_with_stub(cfg):
        built = real_build(cfg)
        built.judge.llm = SlowJudgeLLM()
        return built

    monkeypatch.setattr(Pipeline, "build", staticmethod(build_with_stub))

    refused = cli.main(["rejudge", "--config", str(config)])
    capsys.readouterr()
    assert refused == 3, "without a budget the run is refused, which is exit 3"

    accepted = cli.main(["rejudge", "--config", str(config), "--accept-minutes", "600"])
    said = "".join(capsys.readouterr())
    assert accepted == 0, f"the accepted budget did not reach the gate: {said!r}"
    assert "re-judged" in said


def test_the_cli_offers_the_budget_flag():
    """A refusal that names a flag the command does not have is a dead end."""
    parser = __import__("winnow.cli", fromlist=["cli"]).build_parser()
    args = parser.parse_args(["rejudge", "--accept-minutes", "30"])

    assert args.accept_minutes == 30.0
