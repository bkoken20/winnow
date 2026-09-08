"""Claim text must print on a legacy Windows console without crashing.

Windows consoles default to a legacy code page -- cp1252 on English installs, cp1254 on
Turkish, cp932 on Japanese -- and Python encodes stdout with it. Winnow prints claim text
straight to stdout, so any claim containing an accent, an umlaut, a curly quotation mark or a
non-Latin script raises UnicodeEncodeError.

That exception is not in `cli._run`'s list, deliberately: unexpected failures should be loud.
But this one is not unexpected, it is a display-layer problem, and it strikes AFTER the
fetch, the extraction and the judging are all finished -- so the user loses minutes of work
to a traceback about a character.

Measured before the fix: cp1252 crash, cp1254 crash, utf-8 fine. cp1252 is the default on a
plain English Windows install, so this is the common case, not an exotic one.

Found by ingesting a Finnish song whose captions YouTube had labelled Korean.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Finnish, Turkish, Korean -- and a curly quote, which yt-dlp emits routinely.
NON_ASCII = (
    "Ääninopeus kasvaa kun muistikaista riittää\n"
    "Bellek bant genişliği çıkarımı sınırlar\n"
    "메모리 대역폭이 추론 속도를 제한한다\n"
    "The model’s throughput is bandwidth bound\n"
)

CHILD = """
import sys, json
sys.path.insert(0, {root!r})
from winnow import pipeline as P

class LineLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps({{"claims": [{{"claim": l.strip()}} for l in body.splitlines() if l.strip()]}})

_orig = P.Pipeline.build
def build(cfg):
    p = _orig(cfg); p.extractor.llm = LineLLM(); return p
P.Pipeline.build = staticmethod(build)

from winnow import cli
raise SystemExit(cli.main(["--config", {config!r}, "ingest", {talk!r}]))
"""


@pytest.fixture
def scenario(tmp_path):
    (tmp_path / "talk").mkdir()
    (tmp_path / "talk" / "transcript.txt").write_text(NON_ASCII, encoding="utf-8")
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "c.db"),
            "embed_backend": "hashing",
            "packs_root": str(ROOT / "packs"),
            "ingest_extra_passes": [],
        }),
        encoding="utf-8",
    )
    return CHILD.format(
        root=str(ROOT), config=str(config), talk=str(tmp_path / "talk")
    )


@pytest.mark.parametrize("encoding", ["cp1252", "cp1254", "cp932", "ascii"])
def test_ingest_survives_a_console_that_cannot_encode_the_claims(scenario, encoding):
    """cp1252 is the default on English Windows. This is the common case."""
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    result = subprocess.run(
        [sys.executable, "-c", scenario],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )

    assert "UnicodeEncodeError" not in (result.stderr or ""), (
        f"printing claim text crashed on a {encoding} console, after the fetch, the "
        f"extraction and the judging had all completed:\n{result.stderr[-400:]}"
    )
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr[-300:]}"


def test_a_utf8_console_shows_the_characters_intact(scenario):
    """The fix must not mangle output where the console can display it."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", scenario],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    assert result.returncode == 0
    assert "Ääninopeus" in result.stdout, (
        "on a console that can encode them, the characters must survive unaltered"
    )
