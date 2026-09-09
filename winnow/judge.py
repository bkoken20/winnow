"""The verdict layer.

Four axes, of which only novelty is answerable without a language model:

    novelty      new, or a restatement of something the corpus already holds?
    specificity  concrete enough to act on or check?
    evidence     does the source support the claim, or merely assert it?
    flags        scam / funnel / hype / unreviewed-code-execution advice

Tier 0 answers novelty with embeddings alone: no API key, no large model, works on any
machine. Tier 1 adds a language model for the other three axes and for nuanced novelty
("same mechanism, new vocabulary").

Two rules are enforced mechanically rather than left to good intentions:

* **Coverage honesty.** A corpus with almost nothing in it makes everything look new. Below
  `min_for_verdict` claims the novelty result is `unknown`, never `new` -- a blind spot is
  not a discovery.
* **Stamping.** Every verdict records what judged it. Verdicts from different judges are
  not comparable, and a corpus that mixes them without saying so becomes worthless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .embed import Embedder
from .models import (
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNKNOWN,
    NOVELTY_VARIANT,
    Claim,
    Coverage,
    JudgeStamp,
    Verdict,
)
from .store import Store

# Similarity thresholds for tier 0. Above KNOWN, the claim is a restatement; between
# VARIANT and KNOWN it is a recognisable variation; below VARIANT it is new to the corpus.
SIMILARITY_KNOWN = 0.90
SIMILARITY_VARIANT = 0.75

# Below this many claims in a pack, no novelty verdict is issued. Chosen so that a corpus
# has at least covered the obvious ground in its domain before it is allowed to call
# anything new. Configurable per pack.
DEFAULT_MIN_CORPUS = 25

JUDGE_PROMPT_VERSION = "1"

JUDGE_PROMPT = """You are assessing a single claim extracted from source material.

CLAIM:
__CLAIM__

THE MOST SIMILAR CLAIMS ALREADY IN THE READER'S CORPUS:
__NEIGHBOURS__

Assess the claim on three axes and return JSON only, no prose outside it:

{
  "novelty": "new" | "variant" | "known",
  "specificity": "concrete" | "vague",
  "evidence": "supported" | "asserted",
  "flags": [],
  "rationale": "one sentence"
}

Definitions:
- novelty: "known" if the corpus already contains this claim in different words;
  "variant" if it is a recognisable variation or special case of something present;
  "new" only if the corpus contains nothing equivalent. Judge the MECHANISM, not the
  vocabulary -- renamed versions of the same idea are "known".
- specificity: "concrete" if someone could act on or check it; "vague" otherwise.
- evidence: "supported" if the source gives reasoning, data or demonstration;
  "asserted" if it is simply stated with confidence.
- flags: any of "scam", "affiliate-funnel", "hype", "unreviewed-code-execution",
  "unsafe-advice". Empty list if none apply.
"""


@dataclass
class JudgeConfig:
    pack: str
    pack_version: str = "1"
    min_corpus: int = DEFAULT_MIN_CORPUS
    top_k: int = 5
    similarity_known: float = SIMILARITY_KNOWN
    similarity_variant: float = SIMILARITY_VARIANT
    # tier 1
    judge_model: str = ""
    judge_location: str = ""  # "local" | "cloud"
    judge_num_ctx: int = 8192
    # Whether the material stayed on this machine: the address AND the user's declared
    # correction to it. Recorded on every verdict at BOTH tiers, because embeddings go to
    # the same host and `judge_location` is blanked when no judge ran.
    stayed_on_this_machine: bool | None = None


def novelty_from_similarity(similarity: float, config: JudgeConfig) -> str:
    if similarity >= config.similarity_known:
        return NOVELTY_KNOWN
    if similarity >= config.similarity_variant:
        return NOVELTY_VARIANT
    return NOVELTY_NEW


class Judge:
    """Tier 0 by default; pass an llm client to enable tier 1."""

    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        config: JudgeConfig,
        llm=None,
    ):
        self.store = store
        self.embedder = embedder
        self.config = config
        self.llm = llm

    @property
    def tier(self) -> int:
        return 1 if (self.llm and self.config.judge_model) else 0

    def stamp(self) -> JudgeStamp:
        return JudgeStamp(
            tier=self.tier,
            embed_model=self.embedder.name,
            embed_backend=self.embedder.backend,
            judge_model=self.config.judge_model if self.tier == 1 else "",
            judge_location=self.config.judge_location if self.tier == 1 else "",
            prompt_version=JUDGE_PROMPT_VERSION if self.tier == 1 else "",
            pack_version=self.config.pack_version,
            # Deliberately NOT gated on the tier. The judge is blanked at tier 0; where
            # the text went is not.
            stayed_on_this_machine=self.config.stayed_on_this_machine,
        )

    def coverage(self, claim_id: str = "") -> Coverage:
        """How much evidence backs a verdict -- excluding the claim being judged.

        A claim is not evidence about itself. During `rejudge` the claim is already stored,
        so counting the whole corpus overstated every verdict's evidence by one and made
        the two paths disagree: `ingest` judges before storing and reported N, `rejudge`
        reported N+1 for the same claim against the same corpus.

        It matters most at the threshold, where a corpus of exactly `min_corpus` would call
        itself sufficient while every verdict actually rested on one fewer peer than
        claimed.
        """
        stored = self.store.count_claims(self.config.pack)
        if claim_id and self.store.claim_exists(claim_id):
            stored -= 1
        return Coverage(corpus_claims=stored, min_for_verdict=self.config.min_corpus)

    def judge_claim(self, claim: Claim, vector: list[float] | None = None) -> Verdict:
        vector = vector if vector is not None else self.embedder.embed(claim.text)
        neighbours = self.store.similarity_search(
            self.config.pack, vector, top_k=self.config.top_k, exclude_claim_id=claim.id
        )
        similarity = neighbours[0].similarity if neighbours else 0.0
        coverage = self.coverage(claim.id)

        if not coverage.sufficient:
            # The corpus cannot support a novelty claim. Saying "new" here would be
            # reporting a blind spot as a discovery.
            return Verdict(
                claim_id=claim.id,
                novelty=NOVELTY_UNKNOWN,
                similarity=similarity,
                neighbours=neighbours,
                coverage=coverage,
                judge=self.stamp(),
                rationale=(
                    f"corpus holds {coverage.corpus_claims} claims for pack "
                    f"'{self.config.pack}'; {coverage.min_for_verdict} needed before a "
                    "novelty verdict is meaningful"
                ),
            )

        novelty = novelty_from_similarity(similarity, self.config)

        if self.tier == 0:
            return Verdict(
                claim_id=claim.id,
                novelty=novelty,
                similarity=similarity,
                neighbours=neighbours,
                coverage=coverage,
                judge=self.stamp(),
                rationale=f"nearest corpus claim similarity {similarity:.3f}",
            )

        return self._judge_with_llm(claim, neighbours, similarity, coverage, novelty)

    def _judge_with_llm(self, claim, neighbours, similarity, coverage, fallback_novelty) -> Verdict:
        neighbour_text = (
            "\n".join(f"- ({n.similarity:.2f}) {n.text}" for n in neighbours) or "(none)"
        )
        prompt = JUDGE_PROMPT.replace("__CLAIM__", claim.text).replace(
            "__NEIGHBOURS__", neighbour_text
        )
        raw = self.llm.generate(
            self.config.judge_model,
            prompt,
            num_ctx=self.config.judge_num_ctx,
            as_json=True,
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        # `["new"]`, `"new"`, `42` and `null` are all VALID JSON, so they sail past the
        # decode error above and used to reach `parsed.get` -- which lists and strings do
        # not have. That raised AttributeError, which the CLI does not catch, so a judge
        # answering in the wrong shape produced a traceback after every claim had already
        # been extracted. The fallback exists for exactly this kind of output; it just has
        # to recognise the cases that happen to parse.
        if not isinstance(parsed, dict):
            # Fall back to the tier-0 answer rather than inventing one, and say so.
            return Verdict(
                claim_id=claim.id,
                novelty=fallback_novelty,
                similarity=similarity,
                neighbours=neighbours,
                coverage=coverage,
                judge=self.stamp(),
                rationale="judge model returned unusable output; fell back to similarity",
            )

        novelty = parsed.get("novelty", fallback_novelty)
        if novelty not in (NOVELTY_NEW, NOVELTY_VARIANT, NOVELTY_KNOWN):
            novelty = fallback_novelty

        return Verdict(
            claim_id=claim.id,
            novelty=novelty,
            similarity=similarity,
            neighbours=neighbours,
            coverage=coverage,
            judge=self.stamp(),
            specificity=str(parsed.get("specificity", "")),
            evidence=str(parsed.get("evidence", "")),
            flags=_as_flags(parsed.get("flags")),
            rationale=str(parsed.get("rationale", "")),
        )


def _as_flags(value) -> list[str]:
    """Whatever the model put in `flags`, as a list of strings.

    `list("scam")` is `['s', 'c', 'a', 'm']`, so a judge answering with a bare string --
    which the prompt asks it not to do, and which a small model does anyway -- produced
    four single-character flags on the verdict.
    """
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]
