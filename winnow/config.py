"""Configuration, and the egress statement that goes with it.

Winnow is local by default: with no configuration at all, nothing leaves the machine. A
cloud judge is opt-in, and when one is enabled the tool says plainly what will be sent
where, because a personal corpus plus a remote model is exactly the combination a user
deserves to be warned about before it happens rather than after.
"""

from __future__ import annotations

import difflib
import json
import os
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from urllib.parse import urlparse

CONFIG_FILENAME = "winnow.json"

DEFAULT_TEXT_MODEL = "qwen2.5:14b-instruct"
DEFAULT_TEXT_NUM_CTX = 32768
DEFAULT_VISION_MODEL = "qwen2.5vl:7b"
DEFAULT_VISION_NUM_CTX = 8192
DEFAULT_EMBED_MODEL = "nomic-embed-text"


@dataclass
class Config:
    pack: str = "ai_tooling"
    corpus_path: str = "winnow.db"
    notes_path: str = ""
    # Where material fetched from a URL is kept. Cached per URL, so re-running a link does
    # not re-download it, and so you can see what was fetched.
    cache_path: str = "winnow-cache"
    # Caption languages passed to yt-dlp when fetching from a URL.
    caption_languages: str = "en.*"

    ollama_host: str = "http://localhost:11434"
    text_model: str = DEFAULT_TEXT_MODEL
    text_num_ctx: int = DEFAULT_TEXT_NUM_CTX
    vision_model: str = DEFAULT_VISION_MODEL
    vision_num_ctx: int = DEFAULT_VISION_NUM_CTX
    # Frame sampling, used only when the pack sets `use_frames`. One vision call per frame,
    # several seconds each, on a path with no cost gate -- so the default is deliberately
    # modest. NOT measured: no experiment in this repository establishes how many frames are
    # worth describing, unlike the chunking defaults. Treat these as conservative guesses.
    frame_every_seconds: int = 60
    max_frames: int = 20
    # Text handed to the model per extraction call. Small on purpose -- measured, see
    # experiments/CHUNK_SIZE.md. Not the same question as what the context window holds.
    chunk_chars: int = 2000
    # Extra extraction passes at OTHER chunk sizes, re-reading the same text. Different
    # boundaries put different sentences beside each other, so each pass finds claims the
    # others miss. Measured (experiments/TWO_PASS.md, experiments/THIRD_PASS.md):
    #
    #   passes                 documentation      20-minute talk
    #   2,000                    44%  13.9 min      39%  1.7 min
    #   +1,000                   78%  31.6 min      71%  3.4 min
    #   +1,000 +4,000            90%  41.8 min      92%  4.5 min
    #
    # On for ingest, where the third pass costs about a minute. Off for indexing, where the
    # same choice is 11.6 hours against 34.8 on a 7.5 MB corpus. Empty list disables.
    ingest_extra_passes: list[int] = field(default_factory=lambda: [1000, 4000])
    index_extra_passes: list[int] = field(default_factory=list)
    duplicate_threshold: float = 0.93

    embed_backend: str = "ollama"
    embed_model: str = DEFAULT_EMBED_MODEL

    # Tier 1. Empty judge_model means tier 0 -- embeddings only, nothing leaves the box.
    judge_model: str = ""
    judge_num_ctx: int = 8192
    judge_location: str = "local"  # "local" | "cloud"

    packs_root: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Read a config file, warning loudly about keys it does not recognise.

        Unknown keys used to be dropped in silence, which turned a typo into a setting that
        appeared to apply and did not. That is worst for `text_num_ctx`, where the default
        silently truncates every prompt and extraction then reports finding nothing -- the
        exact failure the documentation calls the most costly to get wrong.
        """
        candidate = Path(path) if path else Path(CONFIG_FILENAME)
        if not candidate.exists():
            return cls()
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(f"{candidate}: {exc.msg}", exc.doc, exc.pos) from None
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known)
        if unknown:
            for key in unknown:
                suggestion = difflib.get_close_matches(key, known, n=1, cutoff=0.6)
                hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
                warnings.warn(
                    f"{candidate}: unknown setting '{key}' ignored{hint}",
                    UserWarning,
                    stacklevel=2,
                )
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else Path(CONFIG_FILENAME)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target

    # -- privacy ---------------------------------------------------------------

    @property
    def host_is_local(self) -> bool:
        """Does `ollama_host` actually point at this machine?

        Everything -- transcripts, notes, every extracted claim -- is POSTed to this host.
        A privacy statement that ignores where it points can announce "nothing leaves this
        machine" while sending every word to another box, which is worse than saying
        nothing at all.
        """
        parsed = urlparse(self.ollama_host)
        host = (parsed.hostname or "").lower()
        if not parsed.scheme or not host:
            # Unparseable, or missing its scheme (`ollama.example.com:11434` parses to no
            # hostname at all). Refuse to call that local: this check fails CLOSED, because
            # a privacy statement that fails open is worse than having none.
            return False
        return host in ("localhost", "127.0.0.1", "::1")

    @property
    def is_fully_local(self) -> bool:
        return (
            self.host_is_local
            and self.judge_location != "cloud"
            and self.embed_backend != "cloud"
        )

    def egress_statement(self) -> str:
        """Exactly what leaves this machine under the current settings."""
        if self.is_fully_local:
            return (
                "FULLY LOCAL. Nothing leaves this machine: extraction, embeddings and any "
                f"judging run against Ollama at {self.ollama_host}. Your notes and the "
                "claims extracted from them are never transmitted."
            )

        reasons = []
        if not self.host_is_local:
            parsed = urlparse(self.ollama_host)
            if not parsed.scheme or not parsed.hostname:
                reasons.append(
                    f"ollama_host ({self.ollama_host!r}) cannot be read as a URL -- it needs "
                    "a scheme, e.g. 'http://localhost:11434'. Until it is fixed, where your "
                    "data would go cannot be determined, so it is not being called local"
                )
            else:
                reasons.append(
                    f"ollama_host points at '{parsed.hostname}', which is not this machine -- "
                    "EVERYTHING goes there: the full text of every note and transcript you "
                    "process, and every claim extracted from them"
                )
        if self.judge_location == "cloud" and self.judge_model:
            reasons.append(
                f"a cloud judge ('{self.judge_model}') is declared, so the text of each "
                "claim judged, plus the most similar claims from your corpus, is sent to it"
            )
        elif self.judge_location == "cloud":
            reasons.append(
                "judge_location is 'cloud' but judge_model is empty, so no judging happens "
                "at all and this setting currently does nothing"
            )
        if self.embed_backend == "cloud":
            reasons.append("embed_backend is set to 'cloud'")

        return "NOT FULLY LOCAL. " + "; ".join(reasons) + "."

    def resolved_notes_path(self) -> Path | None:
        raw = self.notes_path or os.environ.get("WINNOW_NOTES", "")
        return Path(raw) if raw else None
