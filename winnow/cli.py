"""Command line interface.

    winnow status                     what is configured, what is in the corpus, what leaves the box
    winnow init                       write a starter winnow.json
    winnow index <folder>             build the corpus from a folder of notes
    winnow ingest <url|path>          judge new material against the corpus
    winnow rejudge                    re-judge every claim against the corpus as it stands
    winnow packs                      list available domain packs
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from .config import CONFIG_FILENAME, Config
from .cost import RunRefused
from .llm import OllamaError
from .acquire import (
    AcquisitionFailed,
    YtDlpMissing,
    cache_dir_for,
    fetch,
    looks_like_url,
    why_not_a_url,
)
from .media import find_media_file
from .pipeline import CorpusEmbeddingMismatch
from .models import NOVELTY_KNOWN, NOVELTY_NEW, NOVELTY_UNKNOWN, NOVELTY_VARIANT
from .packs import InvalidPack, available_packs, find_pack

SYMBOL = {
    NOVELTY_NEW: "NEW    ",
    NOVELTY_VARIANT: "VARIANT",
    "known": "known  ",
    NOVELTY_UNKNOWN: "?      ",
}


def _run(func, args) -> int:
    """Turn predictable failures into a sentence and an exit code, never a traceback.

    Mistyping a folder is the most likely thing a user will do, and it produced a Python
    stack trace. A tool that answers an ordinary mistake with a traceback reads as broken
    rather than as strict, and buries the one line that would have helped.

    Genuinely unexpected exceptions are deliberately NOT caught: a crash nobody planned for
    should be loud and complete, not flattened into a tidy message that hides where it came
    from.
    """
    try:
        return func(args)
    except CorpusEmbeddingMismatch as exc:
        print(f"corpus/model mismatch: {exc}", file=sys.stderr)
        return 6
    except InvalidPack as exc:
        print(f"invalid pack: {exc}", file=sys.stderr)
        return 7
    except YtDlpMissing as exc:
        print(str(exc), file=sys.stderr)
        return 8
    except AcquisitionFailed as exc:
        print(f"could not fetch: {exc}", file=sys.stderr)
        return 9
    except RunRefused as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except OllamaError as exc:
        print(f"Ollama: {exc}", file=sys.stderr)
        # A 404 means the server answered, so telling them to check that it is running
        # wastes the one moment they are reading the error. It means a model was never
        # pulled, and the message above already names which one.
        if getattr(exc, "status", None) == 404:
            print(
                "  That model is not pulled. Pull it, then re-run:\n"
                "    ollama pull <the model named above>\n"
                "  `winnow status` lists the models this configuration expects.",
                file=sys.stderr,
            )
        else:
            print(
                "  Is it running? Check with: curl -s http://localhost:11434/api/tags",
                file=sys.stderr,
            )
        return 4
    except NotADirectoryError as exc:
        print(f"not a folder: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"not found: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"malformed JSON: {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"permission denied: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"corpus database error: {exc}", file=sys.stderr)
        print(f"  corpus path: {Config.load(args.config).corpus_path}", file=sys.stderr)
        return 5


def cmd_status(args) -> int:
    """Report configuration and corpus health.

    Returns 6 -- the same code the pipeline raises for it -- when the corpus was built with
    a different embedding model, because a command that prints UNUSABLE and exits 0 lets
    `winnow status && winnow ingest ...` proceed on a corpus that cannot be searched. It
    still never crashes: every other failure is caught and reported as text.
    """
    config = Config.load(args.config)
    unusable = False
    print(f"pack          : {config.pack}")
    print(f"corpus        : {config.corpus_path}")
    print(f"notes         : {config.resolved_notes_path() or '(not set)'}")
    print(f"text model    : {config.text_model} (num_ctx {config.text_num_ctx})")
    print(f"embeddings    : {config.embed_model} via {config.embed_backend}")
    print(f"judge         : {config.judge_model or '(tier 0 -- embeddings only)'}")
    print()
    print("PRIVACY:", config.egress_statement())
    print()

    try:
        from .store import Store

        store = Store(config.corpus_path)
        total = store.count_claims(config.pack)
        pack = find_pack(config.pack, Path(config.packs_root) if config.packs_root else None)
        print(f"corpus holds  : {total} claims for pack '{config.pack}'")
        if total < pack.min_corpus:
            print(
                f"              : below the {pack.min_corpus}-claim minimum, so novelty "
                "verdicts will report 'unknown' rather than guess"
            )

        # Status is where someone looks when results seem wrong, so it has to surface the
        # one condition that makes a full corpus behave like an empty one. It builds its
        # own Store rather than a Pipeline, so it does not get the constructor's check for
        # free and has to ask the same question itself.
        foreign = sorted(store.embed_models_in_use(config.pack) - {config.embed_model})
        if foreign:
            unusable = True
            print(
                f"              : UNUSABLE -- these claims were embedded with "
                f"{', '.join(repr(m) for m in foreign)}, not {config.embed_model!r}. "
                "They cannot be compared against anything, so every claim would look new. "
                "Set embed_model back, or start a fresh corpus and re-index."
            )
        store.close()
    except Exception as exc:  # noqa: BLE001 - status must never crash
        print(f"corpus        : unreadable ({exc})")
    return 6 if unusable else 0


def cmd_init(args) -> int:
    """Write a starter config -- and refuse to clobber one that already exists.

    `init` used to load the existing file and write it back. Known settings survived that
    round trip; anything else did not. A user whose config carried `"_comment": "tuned for
    my corpus, do not change"` lost the note by running a command that reads as harmless.

    Rewriting a file the user already owns is not what "init" means. It now writes only
    when there is nothing there, and `--force` is the deliberate way to start over.
    """
    path = Path(args.config) if args.config else Path(CONFIG_FILENAME)

    if path.exists() and not args.force:
        print(f"{path} already exists -- not overwriting it.", file=sys.stderr)
        print("  To see the current settings:  winnow status", file=sys.stderr)
        print("  To replace it with defaults:  winnow init --force", file=sys.stderr)
        return 2

    written = Config().save(path)
    print(f"wrote {written}")
    print("Edit it to point `notes_path` at your notes folder, then run: winnow index")
    return 0


def cmd_packs(args) -> int:
    config = Config.load(args.config)
    root = Path(config.packs_root) if config.packs_root else None
    names = available_packs(root)
    if not names:
        # `packs/` sits beside the package rather than inside it, so a non-editable
        # `pip install .` installs the code and leaves the packs behind. Every command then
        # fails, and "no packs found" reads as "this project ships no packs". Found by
        # actually installing it both ways.
        print("no packs found.", file=sys.stderr)
        print(
            "  Winnow is distributed by clone, and its packs live beside the package rather\n"
            "  than inside it -- so `pip install .` installs the code without them.\n"
            "  From your clone, run:  pip install -e .   (note the -e)\n"
            "  Or set `packs_root` in winnow.json to the folder holding your packs.",
            file=sys.stderr,
        )
        return 1
    for name in names:
        pack = find_pack(name, root)
        marker = "*" if name == config.pack else " "
        print(f" {marker} {name:<16} v{pack.version}  {pack.description}")
    return 0


def cmd_index(args) -> int:
    from .pipeline import Pipeline

    config = Config.load(args.config)
    folder = Path(args.folder) if args.folder else config.resolved_notes_path()
    if not folder:
        print("no notes folder given and none configured (set notes_path)", file=sys.stderr)
        return 2
    if not folder.exists():
        print(f"no such folder: {folder}", file=sys.stderr)
        return 2
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 2

    pipeline = Pipeline.build(config)
    try:
        result = pipeline.index_notes_folder(folder, accept_minutes=args.accept_minutes)
    finally:
        pipeline.close()

    if result["files"] == 0:
        print("nothing new to index")
        return 0
    if result["projection"]:
        print(result["projection"].describe())
    # `claims` is what was STORED: near-duplicates of something already in the
    # corpus are extracted, judged, and then not kept.
    print(f"indexed {result['files']} files -> {result['claims']} claims stored")
    return 0


def cmd_ingest(args) -> int:
    from .pipeline import Pipeline

    config = Config.load(args.config)

    if looks_like_url(args.path):
        # A link is the common case: fetch its captions, then treat the result exactly as
        # if the user had produced the folder themselves. Cached per URL.
        target = cache_dir_for(args.path, Path(config.cache_path))
        cached = target.exists() and any(target.iterdir())
        # A cache holding only captions does not satisfy --with-video. Deciding the hit on
        # "the folder is non-empty" meant the second of these did nothing at all:
        #     winnow ingest <url>                # captions cached
        #     winnow ingest <url> --with-video   # "using cached material", no video
        # and frame description then no-opped, correctly, on the media that was never
        # fetched. The user's explicit request vanished between two layers each behaving
        # as designed.
        needs_video = args.with_video and find_media_file(target) is None
        if cached and not needs_video and not args.refetch:
            print(f"using cached material in {target}")
        else:
            if cached and needs_video:
                print("cached captions found, but --with-video needs the video too")
            fetch(
                args.path,
                target,
                languages=config.caption_languages,
                with_video=args.with_video,
            )
    else:
        target = Path(args.path)
        if not target.exists():
            # Only now: it is not on disk, so it may be a link the user fumbled. Reporting
            # "no such file or folder: youtu.be\\dQw4w9WgXcQ" answers the wrong question and
            # quotes a string they never typed -- Path() has flipped the separators.
            #
            # Existence is checked FIRST because the reverse order read an existing
            # README.md as a scheme-less link and refused to open a file sitting right
            # there. A thing that exists is that thing, whatever its name resembles.
            problem = why_not_a_url(args.path)
            if problem:
                print(problem, file=sys.stderr)
                return 2
            print(f"no such file or folder: {target}", file=sys.stderr)
            return 2

    pipeline = Pipeline.build(config)
    try:
        claims, verdicts = pipeline.ingest(target)
    finally:
        pipeline.close()

    text_of = {c.id: c.text for c in claims}
    # "extracted" named a different quantity: this is what survived within-batch
    # near-duplicate collapsing, which for a three-pass ingest removes real
    # rewordings of the same assertion.
    print(f"{len(claims)} claims after de-duplication\n")

    if not claims:
        # Finding nothing is a correct answer, and on its own it is indistinguishable from
        # a broken tool. The shipped pack is domain-specific, so the most likely first run
        # by a stranger is a video outside it: the extractor is asked for claims about AI
        # tooling, the material is about something else, and the model rightly returns an
        # empty list for every chunk. Say which pack looked and what it was looking for.
        pack = find_pack(config.pack, Path(config.packs_root) if config.packs_root else None)
        print(f"The '{pack.name}' pack looks for: {pack.description}")
        print(
            "  Nothing of that kind was found in this material. If it is about something\n"
            "  else, that is the expected answer rather than a failure -- a pack is a\n"
            "  prompt and a JSON file, and writing one for your own subject is the point:\n"
            "  docs/DOMAIN_PACKS.md\n"
            "  If the material IS in this pack's domain, the transcript may be empty or\n"
            "  truncated -- check `text_num_ctx` against your model's real context length."
        )
        return 0
    for verdict in verdicts:
        if args.new_only and verdict.novelty != NOVELTY_NEW:
            continue
        label = SYMBOL.get(verdict.novelty, verdict.novelty)
        text = text_of.get(verdict.claim_id, verdict.claim_id)
        if len(text) > 96:
            text = text[:93] + "..."
        print(f"[{label}] {verdict.similarity:.2f}  {text}")
        if verdict.flags:
            print(f"           flags: {', '.join(verdict.flags)}")
        if verdict.novelty == NOVELTY_UNKNOWN:
            print(f"           {verdict.rationale}")
    if verdicts and not verdicts[0].judge.is_trustworthy():
        print("\nWARNING: these verdicts used the hashing embedder (tests only) and mean nothing.")
    return 0


def cmd_rejudge(args) -> int:
    from .pipeline import Pipeline

    config = Config.load(args.config)
    pipeline = Pipeline.build(config)
    try:
        verdicts = pipeline.rejudge()
    finally:
        pipeline.close()
    # "not new" counted everything that was not NEW, which swept in `unknown` --
    # the verdict that means the corpus is too thin to rule at all. On a thin corpus
    # that reported every claim as already known, inverting the rule the whole tool is
    # built on: a blind spot is not a discovery, and it is not prior knowledge either.
    counts = Counter(v.novelty for v in verdicts)
    seen = counts[NOVELTY_KNOWN] + counts[NOVELTY_VARIANT]
    summary = (
        f"re-judged {len(verdicts)} claims: {counts[NOVELTY_NEW]} new, "
        f"{seen} known or variant"
    )
    if counts[NOVELTY_UNKNOWN]:
        summary += (
            f", {counts[NOVELTY_UNKNOWN]} unknown "
            "(corpus below the pack's minimum, so no novelty verdict was issued)"
        )
    print(summary)
    return 0



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winnow",
        description="Give it a YouTube link; it tells you what the video says that you "
                    "do not already know.",
    )
    parser.add_argument("--config", default=None, help="path to winnow.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="configuration, corpus size, and privacy posture").set_defaults(
        func=cmd_status
    )
    p_init = sub.add_parser("init", help="write a starter winnow.json")
    p_init.add_argument(
        "--force", action="store_true",
        help="replace an existing config with defaults (discards what is there)",
    )
    p_init.set_defaults(func=cmd_init)
    sub.add_parser("packs", help="list domain packs").set_defaults(func=cmd_packs)

    p_index = sub.add_parser("index", help="build the corpus from a folder of notes")
    p_index.add_argument("folder", nargs="?", default=None)
    p_index.add_argument(
        "--accept-minutes",
        type=float,
        default=None,
        help="accept a projected run of this many minutes (shown to you first)",
    )
    p_index.set_defaults(func=cmd_index)

    p_ingest = sub.add_parser(
        "ingest", help="judge new material: a URL, a transcript, or a folder"
    )
    p_ingest.add_argument("path", help="a video URL, or a path to a transcript or folder")
    p_ingest.add_argument(
        "--with-video", action="store_true",
        help="also download the video, so frames can be described (much larger)",
    )
    p_ingest.add_argument(
        "--refetch", action="store_true", help="ignore cached material for this URL"
    )
    p_ingest.add_argument("--new-only", action="store_true", help="show only novel claims")
    p_ingest.set_defaults(func=cmd_ingest)

    sub.add_parser("rejudge", help="re-judge all claims against the current corpus").set_defaults(
        func=cmd_rejudge
    )
    return parser


def make_output_encodable() -> None:
    """Stop a console's code page from destroying a finished run.

    Windows consoles default to a legacy code page -- cp1252 on English installs, cp1254 on
    Turkish, cp932 on Japanese -- and Python encodes stdout with it. Winnow prints claim
    text, so one accent, umlaut, curly quotation mark or non-Latin script raised
    UnicodeEncodeError: a traceback about a character, AFTER the fetch, the extraction and
    the judging had all completed. cp1252 is the default on a plain English Windows install,
    so this was the common case rather than an exotic one.

    UTF-8 first, because a modern terminal displays it correctly. Where the stream will not
    take it, fall back to replacing the characters it cannot encode -- a mangled glyph is a
    poor outcome; losing the whole run to it is a worse one.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # a pipe or capture object without the 3.7+ API
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, LookupError, OSError):
            try:
                reconfigure(errors="replace")
            except (ValueError, LookupError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    make_output_encodable()
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
