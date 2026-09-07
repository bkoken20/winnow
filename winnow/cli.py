"""Command line interface.

    winnow status                     what is configured, what is in the corpus, what leaves the box
    winnow init                       write a starter winnow.json
    winnow index <folder>             build the corpus from a folder of notes
    winnow ingest <path>              judge new material against the corpus
    winnow rejudge                    re-judge every claim against the corpus as it stands
    winnow packs                      list available domain packs
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .config import Config
from .cost import RunRefused
from .llm import OllamaError
from .models import NOVELTY_NEW, NOVELTY_UNKNOWN, NOVELTY_VARIANT
from .packs import available_packs, find_pack

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
    except RunRefused as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except OllamaError as exc:
        print(f"Ollama: {exc}", file=sys.stderr)
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
    config = Config.load(args.config)
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
        store.close()
    except Exception as exc:  # noqa: BLE001 - status must never crash
        print(f"corpus        : unreadable ({exc})")
    return 0


def cmd_init(args) -> int:
    config = Config.load(args.config)
    path = config.save(args.config)
    print(f"wrote {path}")
    print("Edit it to point `notes_path` at your notes folder, then run: winnow index")
    return 0


def cmd_packs(args) -> int:
    config = Config.load(args.config)
    root = Path(config.packs_root) if config.packs_root else None
    names = available_packs(root)
    if not names:
        print("no packs found")
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
    print(f"indexed {result['files']} files -> {result['claims']} claims")
    return 0


def cmd_ingest(args) -> int:
    from .pipeline import Pipeline

    config = Config.load(args.config)
    target = Path(args.path)
    if not target.exists():
        print(f"no such file or folder: {target}", file=sys.stderr)
        return 2

    pipeline = Pipeline.build(config)
    try:
        claims, verdicts = pipeline.ingest(target)
    finally:
        pipeline.close()

    text_of = {c.id: c.text for c in claims}
    print(f"{len(claims)} claims extracted\n")
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
    changed = sum(1 for v in verdicts if v.novelty != NOVELTY_NEW)
    print(f"re-judged {len(verdicts)} claims ({changed} not new against the current corpus)")
    return 0



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winnow",
        description="Judge new material against what you already know.",
    )
    parser.add_argument("--config", default=None, help="path to winnow.json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="configuration, corpus size, and privacy posture").set_defaults(
        func=cmd_status
    )
    sub.add_parser("init", help="write a starter winnow.json").set_defaults(func=cmd_init)
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

    p_ingest = sub.add_parser("ingest", help="judge new material (transcript, media, or folder)")
    p_ingest.add_argument("path")
    p_ingest.add_argument("--new-only", action="store_true", help="show only novel claims")
    p_ingest.set_defaults(func=cmd_ingest)

    sub.add_parser("rejudge", help="re-judge all claims against the current corpus").set_defaults(
        func=cmd_rejudge
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args.func, args)


if __name__ == "__main__":
    raise SystemExit(main())
