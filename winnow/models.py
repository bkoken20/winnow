"""Core records: claims, verdicts, and the stamps that make verdicts comparable.

The single most important idea in this module is `JudgeStamp`. Verdicts produced by
different models are *not* comparable — a 7B local judge and a frontier cloud model will
disagree about the same claim. Every verdict therefore carries a full description of what
produced it. Without that, a corpus silently becomes incoherent as the user changes models.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any


NOVELTY_NEW = "new"
NOVELTY_KNOWN = "known"
NOVELTY_VARIANT = "variant"
NOVELTY_UNKNOWN = "unknown"  # corpus too thin to say — see Coverage

NOVELTY_VALUES = (NOVELTY_NEW, NOVELTY_KNOWN, NOVELTY_VARIANT, NOVELTY_UNKNOWN)


@dataclass(frozen=True)
class Source:
    """A piece of material claims were extracted from."""

    id: str
    pack: str
    kind: str  # "media" | "note"
    path: str
    title: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    ingested_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Claim:
    """One extracted assertion. `fields` holds the pack-defined schema values."""

    id: str
    pack: str
    source_id: str
    text: str
    fields: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class JudgeStamp:
    """Exactly what produced a verdict. Recorded on every verdict, always.

    `embed_backend` matters as much as the model name: the hashing backend exists for
    offline tests and produces meaningless similarity, so any verdict carrying it must be
    identifiable as untrustworthy rather than quietly mixed in with real ones.
    """

    tier: int  # 0 = embeddings only, 1 = LLM judge
    embed_model: str
    embed_backend: str  # "ollama" | "hashing"
    judge_model: str = ""  # empty at tier 0
    judge_location: str = ""  # "local" | "cloud" | "" at tier 0
    prompt_version: str = ""
    pack_version: str = ""

    def is_trustworthy(self) -> bool:
        """False when the verdict rests on the offline test backend."""
        return self.embed_backend != "hashing"


@dataclass(frozen=True)
class Coverage:
    """The evidence a verdict rests on.

    A thin corpus produces confident "this is novel!" calls that are really blind spots.
    A verdict that cannot state its evidence base is not a verdict.
    """

    corpus_claims: int  # claims in this pack at judgement time
    min_for_verdict: int  # threshold below which novelty is reported as unknown

    @property
    def sufficient(self) -> bool:
        return self.corpus_claims >= self.min_for_verdict


@dataclass(frozen=True)
class Neighbour:
    claim_id: str
    similarity: float
    text: str


@dataclass(frozen=True)
class Verdict:
    claim_id: str
    novelty: str
    similarity: float  # to the nearest corpus claim; 0.0 when the corpus is empty
    neighbours: list[Neighbour]
    coverage: Coverage
    judge: JudgeStamp
    specificity: str = ""  # tier 1 only
    evidence: str = ""  # tier 1 only
    flags: list[str] = field(default_factory=list)
    rationale: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.novelty not in NOVELTY_VALUES:
            raise ValueError(f"novelty must be one of {NOVELTY_VALUES}, got {self.novelty!r}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)
