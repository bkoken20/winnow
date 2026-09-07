"""Corpus storage: SQLite, one file, no service to run.

Vector search is brute-force cosine over the pack's claims. That is a deliberate choice,
not an oversight: at personal-corpus scale (thousands to low tens of thousands of claims)
a linear scan is milliseconds, and it removes an entire class of dependency, daemon and
index-corruption problems. See `similarity_search` for the measured point at which this
stops being reasonable.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .embed import cosine_similarity
from .models import Claim, Neighbour, Source, Verdict

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    pack        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    path        TEXT NOT NULL,
    title       TEXT,
    meta_json   TEXT NOT NULL DEFAULT '{}',
    ingested_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id          TEXT PRIMARY KEY,
    pack        TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    text        TEXT NOT NULL,
    fields_json TEXT NOT NULL DEFAULT '{}',
    embedding   BLOB,
    embed_model TEXT,
    created_at  REAL NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources (id)
);

CREATE TABLE IF NOT EXISTS verdicts (
    claim_id      TEXT NOT NULL,
    novelty       TEXT NOT NULL,
    similarity    REAL NOT NULL,
    specificity   TEXT,
    evidence      TEXT,
    flags_json    TEXT NOT NULL DEFAULT '[]',
    rationale     TEXT,
    neighbours_json TEXT NOT NULL DEFAULT '[]',
    coverage_json TEXT NOT NULL,
    judge_json    TEXT NOT NULL,
    created_at    REAL NOT NULL,
    PRIMARY KEY (claim_id, created_at),
    FOREIGN KEY (claim_id) REFERENCES claims (id)
);

CREATE INDEX IF NOT EXISTS idx_claims_pack ON claims (pack);
CREATE INDEX IF NOT EXISTS idx_claims_source ON claims (source_id);
CREATE INDEX IF NOT EXISTS idx_sources_path ON sources (path);
CREATE INDEX IF NOT EXISTS idx_verdicts_claim ON verdicts (claim_id);
"""

# Above roughly this many claims in one pack, a brute-force scan stops being instant and an
# approximate-nearest-neighbour index starts to be worth its dependency. Documented as a
# limit of this design rather than enforced anywhere.
BRUTE_FORCE_ADVISORY_LIMIT = 50_000


def _pack_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- sources ---------------------------------------------------------------

    def add_source(self, source: Source) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO sources (id, pack, kind, path, title, meta_json, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.pack,
                source.kind,
                str(source.path),
                source.title,
                json.dumps(source.meta),
                source.ingested_at,
            ),
        )
        self.conn.commit()

    def source_paths(self, pack: str) -> set[str]:
        rows = self.conn.execute("SELECT path FROM sources WHERE pack = ?", (pack,))
        return {r["path"] for r in rows}

    # -- claims ----------------------------------------------------------------

    def add_claim(self, claim: Claim, embedding: list[float], embed_model: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO claims"
            " (id, pack, source_id, text, fields_json, embedding, embed_model, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                claim.id,
                claim.pack,
                claim.source_id,
                claim.text,
                json.dumps(claim.fields),
                _pack_vector(embedding),
                embed_model,
                claim.created_at,
            ),
        )
        self.conn.commit()

    def count_claims(self, pack: str | None = None) -> int:
        if pack:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM claims WHERE pack = ?", (pack,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM claims").fetchone()
        return int(row["n"])

    def claim_exists(self, claim_id: str) -> bool:
        """Is this claim already stored? Indexed primary-key lookup, so effectively free."""
        row = self.conn.execute("SELECT 1 FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return row is not None

    def iter_claims(self, pack: str) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, text, fields_json, source_id FROM claims WHERE pack = ?", (pack,)
        )

    def measure_scan_cost(self, pack: str, vector: list[float]) -> float:
        """Seconds one similarity scan costs, PER CLAIM already stored.

        Used to project de-duplication cost across an indexing run. Returns 0.0 for an
        empty corpus, where there is nothing to scan and nothing to project.
        """
        import time

        stored = self.count_claims(pack)
        if stored == 0:
            return 0.0
        started = time.perf_counter()
        self.similarity_search(pack, vector, top_k=1)
        return (time.perf_counter() - started) / stored

    def embed_models_in_use(self, pack: str) -> set[str]:
        """Which embedding models produced the vectors already stored for this pack.

        Vectors from different models are not comparable, and mismatched dimensions are
        skipped outright during search -- so a corpus embedded with one model is entirely
        INVISIBLE to another. This is how that is detected before it silently ruins every
        verdict.
        """
        rows = self.conn.execute(
            "SELECT DISTINCT embed_model FROM claims WHERE pack = ? AND embed_model IS NOT NULL",
            (pack,),
        )
        return {r["embed_model"] for r in rows if r["embed_model"]}

    # -- search ----------------------------------------------------------------

    def similarity_search(
        self, pack: str, vector: list[float], top_k: int = 5, exclude_claim_id: str = ""
    ) -> list[Neighbour]:
        """Nearest claims in this pack by cosine similarity.

        Brute force: every claim in the pack is compared. Fine to the advisory limit above.
        """
        rows = self.conn.execute(
            "SELECT id, text, embedding FROM claims WHERE pack = ? AND embedding IS NOT NULL",
            (pack,),
        ).fetchall()

        scored: list[Neighbour] = []
        for row in rows:
            if row["id"] == exclude_claim_id:
                continue
            stored = _unpack_vector(row["embedding"])
            if len(stored) != len(vector):
                # Embedding model changed under the corpus; skip rather than crash, but
                # this is why the embed model is recorded per claim.
                continue
            scored.append(
                Neighbour(
                    claim_id=row["id"],
                    similarity=cosine_similarity(vector, stored),
                    text=row["text"],
                )
            )

        scored.sort(key=lambda n: n.similarity, reverse=True)
        return scored[:top_k]

    # -- verdicts --------------------------------------------------------------

    def add_verdict(self, verdict: Verdict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO verdicts"
            " (claim_id, novelty, similarity, specificity, evidence, flags_json, rationale,"
            "  neighbours_json, coverage_json, judge_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                verdict.claim_id,
                verdict.novelty,
                verdict.similarity,
                verdict.specificity,
                verdict.evidence,
                json.dumps(verdict.flags),
                verdict.rationale,
                json.dumps([asdict(n) for n in verdict.neighbours]),
                json.dumps(asdict(verdict.coverage)),
                json.dumps(asdict(verdict.judge)),
                verdict.created_at,
            ),
        )
        self.conn.commit()

    def latest_verdicts(self, pack: str, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT v.* FROM verdicts v JOIN claims c ON c.id = v.claim_id"
            " WHERE c.pack = ? ORDER BY v.created_at DESC LIMIT ?",
            (pack, limit),
        ).fetchall()
