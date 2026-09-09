"""Embedding backends.

Novelty detection is a similarity problem, not a reasoning problem: "have I seen this
before" is answered better and far more cheaply by nearest-neighbour search than by asking
a language model. That is why tier 0 works with no API key and no large model.

Two backends:

* `ollama`   - a real local embedding model. The default, and the only one whose verdicts
               mean anything.
* `hashing`  - a deterministic offline stand-in for tests. It produces *meaningless*
               similarity. It must never be selected by accident, so it is never a
               fallback: a failing ollama backend raises rather than degrading into it,
               and any verdict computed with it is stamped so it can be identified later.
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Protocol

from .config import EMBED_BACKENDS, InvalidConfiguration
from .llm import OllamaClient

DEFAULT_EMBED_MODEL = "nomic-embed-text"
HASHING_DIMS = 256


class Embedder(Protocol):
    name: str
    backend: str

    def embed(self, text: str) -> list[float]: ...


@dataclass
class OllamaEmbedder:
    """Real embeddings from a local model."""

    model: str = DEFAULT_EMBED_MODEL
    client: OllamaClient | None = None
    backend: str = "ollama"

    def __post_init__(self) -> None:
        self.client = self.client or OllamaClient()

    @property
    def name(self) -> str:
        return self.model

    def embed(self, text: str) -> list[float]:
        # No try/except: if the embedding model is unavailable we must fail loudly rather
        # than silently substituting the meaningless hashing backend.
        return self.client.embed(self.model, text)


@dataclass
class HashingEmbedder:
    """Deterministic, offline, and semantically meaningless. Tests only.

    Similarity between two different texts under this backend carries no information about
    whether they mean the same thing. It exists so the pipeline can be tested end to end
    without a running model, nothing more.
    """

    dims: int = HASHING_DIMS
    backend: str = "hashing"

    @property
    def name(self) -> str:
        return f"hashing-{self.dims}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for token in _tokenise(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = struct.unpack("<Q", digest)[0] % self.dims
            vector[index] += 1.0
        return _l2_normalise(vector)


def _tokenise(text: str) -> list[str]:
    return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]


def _l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def build_embedder(backend: str, model: str = DEFAULT_EMBED_MODEL, host: str | None = None) -> Embedder:
    if backend == "ollama":
        client = OllamaClient(host=host) if host else OllamaClient()
        return OllamaEmbedder(model=model, client=client)
    if backend == "hashing":
        return HashingEmbedder()
    # The valid names come from the same tuple the configuration validates against, so
    # this message and that check cannot drift apart. A bare ValueError here reached the
    # user as a traceback; it is a setting with a bad value, which has an exit code.
    raise InvalidConfiguration(
        f"unknown embedding backend {backend!r}; embed_backend must be one of: "
        f"{', '.join(EMBED_BACKENDS)}"
    )
