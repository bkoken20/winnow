"""Claim extraction: text in, structured claims out.

The same code path serves both media transcripts and the seed corpus. That symmetry is the
point -- a note and a talk both contain claims, and there is no reason to build two
subsystems to pull them out.

Long inputs are chunked. Chunking exists because a model handed a whole document returns
its topic sentences and drops the specifics -- see DEFAULT_CHUNK_CHARS below for the
measurements. Chunk size is therefore chosen for extraction quality and merely CAPPED by
the context window; the two are different questions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .config import InvalidConfiguration
from .models import Claim
from .packs import Pack

# Rough characters-per-token for English prose. Used only to keep a chunk comfortably
# inside the declared context window, with room for the prompt and the response.
CHARS_PER_TOKEN = 4
PROMPT_OVERHEAD_TOKENS = 1200
RESPONSE_HEADROOM_TOKENS = 1500

# How much text to hand the model at once.
#
# This is NOT derived from the context window, and that distinction is the whole point: the
# context window says what FITS, which is a different question from what the model will
# actually enumerate. Measured on real material with qwen2.5:14b-instruct -- full method,
# caveats and both result tables in experiments/CHUNK_SIZE.md:
#
#   written documentation (3 docs, ~150 KB)      spoken transcript (25 min talk, 21 KB)
#   chunk    distinct   coverage   seconds       chunk    distinct   coverage   seconds
#   1,000         337        53%      1030       1,000          28        37%        94
#   2,000         275        44%       853       2,000          29        39%       106
#   4,000         192        31%       609       4,000          19        25%        68
#  12,000          67        11%       249      40,000           7         9%        30
# 120,000          24         4%       135        (whole transcript in one call)
#
# Near-duplicate rate was 0-3% everywhere, so the extra claims at small sizes are genuinely
# distinct rather than repetition. Given a whole document at once the model returns its topic
# sentences and drops the specifics -- which for a novelty tool is the worst possible bias,
# because headline claims are the ones already in any established corpus.
#
# 2,000 is the default because the two source types disagree about the ideal. Dense written
# prose keeps improving down to 1,000 with no plateau found; speech peaks at 2,000 and gets
# no better below it, plausibly because a spoken claim's subject and its qualifier can sit a
# paragraph apart. 2,000 is the best measured value for speech and a large gain over 4,000
# for documentation, without over-fitting to a single transcript.
#
# Raise or lower it per corpus with `chunk_chars` in winnow.json. For a corpus that is all
# dense written reference material, 1,000 measurably finds more, at ~20% more time.
DEFAULT_CHUNK_CHARS = 2_000


def context_capacity_chars(num_ctx: int) -> int:
    """The largest chunk that fits in this context window, prompt and response included."""
    usable = num_ctx - PROMPT_OVERHEAD_TOKENS - RESPONSE_HEADROOM_TOKENS
    if usable < 500:
        raise InvalidConfiguration(
            f"text_num_ctx={num_ctx} is too small to extract from: after the prompt and "
            f"room for a reply there are {usable} tokens left. Raise text_num_ctx to the "
            "model's real context window, or use a model with a larger one."
        )
    return usable * CHARS_PER_TOKEN


def chunk_size_for(num_ctx: int, preferred: int = DEFAULT_CHUNK_CHARS) -> int:
    """Chunk size to extract with: the preferred size, capped by what actually fits.

    The cap matters only for small-context models. For anything modern the preferred size
    wins, because thoroughness rather than capacity is what governs extraction quality.
    """
    return min(preferred, context_capacity_chars(num_ctx))


def split_text(text: str, chunk_chars: int) -> list[str]:
    """Split on paragraph boundaries where possible, hard-split only when forced."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > chunk_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(para), chunk_chars):
                chunks.append(para[i : i + chunk_chars].strip())
            continue
        if len(current) + len(para) + 2 > chunk_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def claim_id(pack: str, source_id: str, text: str) -> str:
    digest = hashlib.blake2b(
        f"{pack}\x00{source_id}\x00{text}".encode("utf-8"), digest_size=12
    ).hexdigest()
    return digest


def parse_claims_json(raw: str) -> list[dict]:
    """Parse a model's claim list, tolerating the usual wrapping.

    Models wrap JSON in prose or fences even when asked not to, so the first balanced
    object or array in the output is used.
    """
    raw = raw.strip()
    if not raw:
        return []
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    if isinstance(parsed, dict):
        for key in ("claims", "items", "results"):
            if isinstance(parsed.get(key), list):
                return [c for c in parsed[key] if isinstance(c, dict)]
        return [parsed]
    if isinstance(parsed, list):
        return [c for c in parsed if isinstance(c, dict)]
    return []


@dataclass
class Extractor:
    llm: object
    model: str
    num_ctx: int
    pack: Pack
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    # Additional passes at other chunk sizes. Measured (experiments/TWO_PASS.md): a second
    # pass at a DIFFERENT small size raises coverage far more than a whole-document pass
    # does, because different chunk boundaries put different sentences next to each other
    # and each pass therefore surfaces different claims. Boundary diversity, not synthesis.
    extra_passes: tuple[int, ...] = ()

    @property
    def passes(self) -> list[int]:
        return [self.chunk_chars, *self.extra_passes]

    def extract(self, text: str, source_id: str, *, progress=None) -> list[Claim]:
        """Every claim in `text`, de-duplicated across all passes.

        `progress`, when given, is called once as each pass begins with keyword arguments
        `number`, `total`, `chunks` and `chunk_chars`. It exists because a three-pass
        ingest of a 25-minute talk is about 4.5 minutes (experiments/TWO_PASS.md) during
        which this loop is the only thing happening, and a run that says nothing for four
        minutes is indistinguishable from one that has hung.

        A callback rather than a print: this is a library, and where output goes is the
        caller's decision. The passes were previously flattened into a single list of
        chunks before the loop, which is why there was nothing here that knew where one
        pass ended and the next began.

        The loop stays INSIDE one call, and `seen` therefore spans the passes. That is not
        incidental: passes exist to cut the same text at different boundaries, so they
        return the same claim repeatedly on purpose. Measured on a 30-paragraph transcript
        at 2,000 / 1,000 / 4,000 characters -- one call yields 30 claims, three separate
        calls yield 90, of which 60 are exact duplicates that each then cost an embedding,
        a judge call and a corpus row.
        """
        claims: list[Claim] = []
        seen: set[str] = set()
        sizes = self.passes
        for number, size in enumerate(sizes, start=1):
            # The EFFECTIVE size, not the requested one. A small-context model caps the
            # chunk, and reporting the size that was asked for would describe a run that
            # did not happen.
            effective = chunk_size_for(self.num_ctx, size)
            chunks = split_text(text, effective)
            if progress is not None:
                progress(
                    number=number,
                    total=len(sizes),
                    chunks=len(chunks),
                    chunk_chars=effective,
                )
            for chunk in chunks:
                prompt = self.pack.render_extract_prompt(chunk)
                raw = self.llm.generate(
                    self.model, prompt, num_ctx=self.num_ctx, as_json=True
                )
                for item in parse_claims_json(raw):
                    statement = str(
                        item.get("claim") or item.get("statement") or ""
                    ).strip()
                    if not statement:
                        continue
                    cid = claim_id(self.pack.name, source_id, statement)
                    if cid in seen:
                        continue
                    seen.add(cid)
                    fields = {
                        k: v for k, v in item.items() if k not in ("claim", "statement")
                    }
                    claims.append(
                        Claim(
                            id=cid,
                            pack=self.pack.name,
                            source_id=source_id,
                            text=statement,
                            fields=fields,
                        )
                    )
        return claims
