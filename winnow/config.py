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

# The embedding backends that exist. Quoted by the error message and read by the dispatch in
# `embed.build_embedder`, so a name can never appear in one and not the other -- the failure
# this replaces was `embed_backend: "cloud"`, which this module described the privacy
# consequences of at length while `build_embedder` had no such branch at all.
EMBED_BACKENDS = ("ollama", "hashing")
# Where you declare your judging happens. A DECLARATION only: the judge is always
# OllamaClient(host=ollama_host), so this routes nothing -- it selects the warning and is
# recorded in each verdict's stamp.
JUDGE_LOCATIONS = ("local", "cloud")


class InvalidConfiguration(ValueError):
    """A setting whose value cannot be used, named so the CLI can answer with exit code 2.

    Distinct from malformed JSON: the file parsed, and the mistake is in what it says. Both
    are the user's input and both exit 2, but only this one can name the setting.
    """


# Settings that are a SIZE: zero or negative is never a usable value for any of them, and
# zero is the shape a half-edited file takes.
POSITIVE_SETTINGS = (
    "text_num_ctx",
    "vision_num_ctx",
    "judge_num_ctx",
    "chunk_chars",
    "frame_every_seconds",
    "max_frames",
)
# Settings that are a cosine similarity, which cannot leave [0, 1]. `duplicate_threshold:
# 5.0` was accepted in silence and no similarity can reach it, so de-duplication was off and
# nothing in the output said so -- a wrong answer rather than a crash.
UNIT_INTERVAL_SETTINGS = ("duplicate_threshold",)

# `bool` is a subclass of `int`, so a plain isinstance check accepts `true` for a context
# window. JSON has a literal `true`, and a hand-edited file is exactly where it turns up.
_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict),
}
_ARTICLE = {
    "str": "a string",
    "int": "a whole number",
    "float": "a number",
    "list": "a list of whole numbers",
    "dict": "an object",
}


def _declared_kind(annotation) -> str:
    """Which of the five shapes this field declares.

    Read from the annotation the dataclass already carries rather than from a table beside
    it, so a setting added later is type-checked the day it appears instead of the day
    someone remembers to add a row. `from __future__ import annotations` makes these
    strings, hence the text handling.
    """
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    for kind in ("list", "dict", "str", "float", "int"):
        if text.startswith(kind):
            return kind
    return ""


def _validate(data: dict, where: Path) -> None:
    """Refuse a value the code below cannot use, naming the file and the setting.

    Deliberately at the FILE boundary and not in `__post_init__`: a `Config` built directly
    in code stays unvalidated, which is what lets the privacy checks be tested against
    values `load` refuses -- `Config(judge_location="cloutd").is_fully_local` has to be
    provable, and it cannot be if the constructor rejects the argument.

    Deliberately NOT in `cli._run` either, which is where the review suggested catching
    `TypeError` and `ValueError`. Those are what a genuine bug raises, and catching them
    there would answer the next real defect with a tidy "bad input" message.
    """
    for name, spec in Config.__dataclass_fields__.items():
        if name not in data:
            continue
        value = data[name]
        kind = _declared_kind(spec.type)
        if kind and not _CHECKS[kind](value):
            raise InvalidConfiguration(
                f"{where}: {name} must be {_ARTICLE[kind]}, not "
                f"{type(value).__name__} ({value!r})."
            )
        if kind == "list" and not all(
            isinstance(item, int) and not isinstance(item, bool) and item > 0
            for item in value
        ):
            raise InvalidConfiguration(
                f"{where}: {name} is {value!r}. Every entry is a chunk size in characters, "
                "so each must be a whole number greater than zero."
            )
        if name in POSITIVE_SETTINGS and value <= 0:
            raise InvalidConfiguration(
                f"{where}: {name} is {value!r}. It is a size, so it must be greater than "
                "zero."
            )
        if name in UNIT_INTERVAL_SETTINGS and not 0.0 <= value <= 1.0:
            raise InvalidConfiguration(
                f"{where}: {name} is {value!r}. It is a cosine similarity, so it must be "
                "between 0 and 1 -- above 1 nothing is ever a duplicate and the check is "
                "silently off."
            )


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
    # Caption languages passed to yt-dlp when fetching from a URL. `--sub-langs` is a
    # REGEX: the old default "en.*" matched the original track AND YouTube's machine
    # translation of it into English, downloading the same captions twice and hitting the
    # translation endpoint that causes the subtitle 429. "en-orig" is the original alone;
    # Winnow falls back to "en" by itself when a video has no original English track.
    caption_languages: str = "en-orig"

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
    # others miss. Measured (experiments/TWO_PASS.md, including its third-pass addendum):
    #
    #   passes                 documentation      25-minute talk
    #   2,000                    44%  13.9 min      39%  1.7 min
    #   +1,000                   78%  31.6 min      71%  3.4 min
    #   +1,000 +4,000            90%  41.8 min      92%  4.5 min
    #
    # On for ingest, where the third pass costs about a minute. Off for indexing, where the
    # same choice is projected at 11.6 hours against 34.8 on a 7.5 MB corpus -- projected
    # from measured throughput, not a timed run. Empty list disables.
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
        if not isinstance(data, dict):
            # Well-formed JSON of the wrong shape. A list reached `set(data) - known` and
            # died on `'int' object is not iterable`; a string was worse, iterating into
            # single characters and warning about an unknown setting 'w', then 'i', then
            # 'n'. Neither says the one thing that helps: this file has to be an object.
            raise InvalidConfiguration(
                f"{candidate}: a configuration file must be a JSON object "
                f"({{\"pack\": \"ai_tooling\", ...}}), not a "
                f"{type(data).__name__}."
            )
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
        _validate(data, candidate)
        config = cls(**{k: v for k, v in data.items() if k in known})
        if config.judge_location not in JUDGE_LOCATIONS:
            raise InvalidConfiguration(
                f"{candidate}: judge_location is {config.judge_location!r}, which is not a "
                f"value Winnow understands. Use one of: {', '.join(JUDGE_LOCATIONS)}."
            )
        if config.embed_backend not in EMBED_BACKENDS:
            # Refused HERE, not at first use, because `winnow status` never builds a
            # pipeline: it read this setting, believed it, and printed a privacy statement
            # about a backend that does not exist.
            raise InvalidConfiguration(
                f"{candidate}: embed_backend is {config.embed_backend!r}, which is not a "
                f"backend Winnow has. Use one of: {', '.join(EMBED_BACKENDS)}."
            )
        return config

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
            # `in`, not `!= "cloud"`. The old form passed every OTHER value -- a typo, a
            # capital C, an invented word -- as fully local: a privacy check failing OPEN.
            and self.judge_location == "local"
            # Any backend that is not one of ours, not the single spelling 'cloud'. This
            # said `!= "cloud"`, which described one imagined non-local backend and passed
            # every other unknown value as fully local.
            and self.embed_backend in EMBED_BACKENDS
        )

    def egress_statement(self) -> str:
        """Exactly what leaves this machine under the current settings.

        The README points at `winnow status` as the authority on this question, so this
        string has to be true rather than reassuring. It said "Nothing leaves this machine",
        which was written when the only network code was the Ollama client and stayed there
        after `winnow ingest <url>` learned to fetch captions.
        """
        if self.is_fully_local:
            return (
                "LOCAL, except fetching. Extraction, embeddings and any judging run "
                f"against Ollama at {self.ollama_host}; your notes, transcripts and the "
                "claims extracted from them are never transmitted. The one exception: "
                "`winnow ingest <url>` runs yt-dlp, which contacts that site. It prints "
                "the exact command first, and sends nothing of yours beyond the link you "
                "gave it."
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
        if self.judge_location not in JUDGE_LOCATIONS:
            reasons.append(
                f"judge_location is {self.judge_location!r}, which is not a value Winnow "
                f"understands ({', '.join(JUDGE_LOCATIONS)}); a setting about where your "
                "judging happens that cannot be read is not evidence that it happens here"
            )
        elif self.judge_location == "cloud" and self.judge_model:
            reasons.append(
                f"a cloud judge ('{self.judge_model}') is declared, so the text of each "
                "claim judged, plus the most similar claims from your corpus, is sent to it"
            )
        elif self.judge_location == "cloud":
            reasons.append(
                "judge_location is 'cloud' but judge_model is empty, so no judging happens "
                "at all and this setting currently does nothing"
            )
        if self.embed_backend not in EMBED_BACKENDS:
            # This used to read `== "cloud"` and answer "embed_backend is set to 'cloud'",
            # a description of the privacy consequences of a backend `build_embedder` has
            # no branch for. Claiming a feature in a privacy statement is worse than
            # claiming one in a README.
            reasons.append(
                f"embed_backend is {self.embed_backend!r}, which is not a backend Winnow "
                f"has ({', '.join(EMBED_BACKENDS)}), so what it would do with your text "
                "cannot be stated at all"
            )

        # A headline with nothing after it is worse than no headline: it alarms and does
        # not inform. If `is_fully_local` ever says no for a case with no reason written
        # for it, say that plainly rather than printing "NOT FULLY LOCAL. ."
        if not reasons:
            reasons = [
                "the settings do not add up to a local configuration and this message "
                "cannot say which one is responsible -- run `winnow status` and check "
                "ollama_host, embed_backend and judge_location"
            ]
        return "NOT FULLY LOCAL. " + "; ".join(reasons) + "."

    def resolved_notes_path(self) -> Path | None:
        raw = self.notes_path or os.environ.get("WINNOW_NOTES", "")
        return Path(raw) if raw else None
