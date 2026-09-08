"""What the tool prints must be interpretable from the documentation.

Two separate failures, both found by auditing every printed string and every exit code
against the docs rather than against memory:

1. LABELS THAT DO NOT DESCRIBE THEIR NUMBER. Documentation cannot rescue these; the output
   itself is wrong.
     - "N claims extracted" counts what SURVIVED near-duplicate collapsing, not what was
       extracted. A reader comparing it against the multi-pass numbers in the docs (~19% of
       a merged set are rewordings) is comparing two different quantities.
     - "indexed N files -> M claims" counts what was STORED, after suppression.
     - "M not new against the current corpus" counts `novelty != new`, which INCLUDES
       `unknown`. `unknown` means the corpus is too thin to rule at all. Reporting it as
       "not new" inverts the tool's own rule that a blind spot is not a discovery -- on a
       thin corpus every claim is announced as already known.

2. TEN EXIT CODES, NONE DOCUMENTED. `cli._run` maps predictable failures to 2-9 so a script
   can tell throttling from a bad path from a missing model server. Nothing said so
   anywhere, which makes them unusable and, worse, free to be renumbered by accident.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from winnow import cli

ROOT = Path(__file__).resolve().parent.parent
PACKS_ROOT = ROOT / "packs"
DOCS = "\n".join(
    p.read_text(encoding="utf-8")
    for p in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
)


# -- labels that must describe their number ------------------------------------------


class LineClaimsLLM:
    def generate(self, model, prompt, *, num_ctx, as_json=False):
        body = prompt.split("SOURCE MATERIAL:")[-1].strip()
        return json.dumps(
            {"claims": [{"claim": ln.strip()} for ln in body.splitlines() if ln.strip()]}
        )


def _setup(tmp_path) -> Path:
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "corpus.db"),
            "embed_backend": "hashing",
            "packs_root": str(PACKS_ROOT),
            "ingest_extra_passes": [],
        }),
        encoding="utf-8",
    )
    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text(
        "\n".join(f"topic {i} behaves differently under load" for i in range(6)),
        encoding="utf-8",
    )
    return config


def _stub_llm(monkeypatch):
    from winnow import pipeline as pipeline_module

    original = pipeline_module.Pipeline.build

    def build(config):
        built = original(config)
        built.extractor.llm = LineClaimsLLM()
        return built

    monkeypatch.setattr(pipeline_module.Pipeline, "build", staticmethod(build))


def test_rejudge_does_not_report_unknown_as_not_new(tmp_path, capsys, monkeypatch):
    """A thin corpus cannot rule, and must not be summarised as though it had."""
    _stub_llm(monkeypatch)
    config = _setup(tmp_path)

    cli.main(["--config", str(config), "ingest", str(tmp_path / "talk")])
    capsys.readouterr()

    cli.main(["--config", str(config), "rejudge"])
    output = capsys.readouterr().out

    # The corpus here is far below min_corpus (25), so every verdict is `unknown`.
    assert "not new" not in output, (
        "every claim here is 'unknown' -- the corpus is too thin to rule -- and the summary "
        f"reported them as 'not new'. Output: {output!r}"
    )
    assert "unknown" in output.lower() or "too thin" in output.lower(), (
        "the summary must say the corpus could not rule, not quietly count it as known"
    )


def test_the_ingest_count_says_what_it_counted(tmp_path, capsys, monkeypatch):
    """"extracted" names a different quantity from the one printed."""
    _stub_llm(monkeypatch)
    config = _setup(tmp_path)

    cli.main(["--config", str(config), "ingest", str(tmp_path / "talk")])
    output = capsys.readouterr().out.lower()

    assert "claims extracted" not in output, (
        "the number is what survived near-duplicate collapsing, not what was extracted"
    )


def test_the_index_count_says_what_it_counted(tmp_path, capsys, monkeypatch):
    _stub_llm(monkeypatch)
    config = _setup(tmp_path)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("alpha behaves differently under load", encoding="utf-8")

    cli.main(["--config", str(config), "index", str(notes)])
    output = capsys.readouterr().out.lower()

    assert "-> " in output
    assert "stored" in output, (
        "index reports claims STORED, after near-duplicate suppression; the word has to "
        f"say so. Output: {output!r}"
    )


# -- exit codes ----------------------------------------------------------------------


def _exit_codes_in_run() -> set[int]:
    source = (ROOT / "winnow" / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run":
            return {
                n.value.value
                for n in ast.walk(node)
                if isinstance(n, ast.Return)
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, int)
            }
    raise AssertionError("cli._run not found")


def test_every_failure_exit_code_is_documented():
    """A script cannot act on a code it cannot look up."""
    codes = _exit_codes_in_run()
    assert codes, "guard: no exit codes found, so this check would pass vacuously"

    undocumented = sorted(c for c in codes if not re.search(rf"^\| `{c}` \|", DOCS, re.MULTILINE))
    assert not undocumented, (
        f"cli._run returns {sorted(codes)}; these are in no table in README or docs/: "
        f"{undocumented}"
    )


def test_the_documented_codes_still_exist_in_the_code():
    """The reverse drift: a table row for a code nothing returns any more."""
    documented = {int(m) for m in re.findall(r"^\| `([2-9])` \|", DOCS, re.MULTILINE)}
    assert documented, "guard: no exit-code table found"
    stale = sorted(documented - _exit_codes_in_run() - {0, 1})
    assert not stale, f"documented exit codes that nothing returns: {stale}"


# -- status must not report success while reporting UNUSABLE -------------------------


def test_status_exits_nonzero_when_the_corpus_is_unusable(tmp_path, capsys):
    """A health check that passes on a broken corpus is worse than none."""
    from winnow.models import Claim, Source
    from winnow.store import Store
    from winnow.embed import HashingEmbedder

    corpus = tmp_path / "corpus.db"
    store = Store(corpus)
    embedder = HashingEmbedder()
    store.add_source(Source(id="s", pack="ai_tooling", kind="note", path="/x"))
    store.add_claim(
        Claim(id="c1", pack="ai_tooling", source_id="s", text="a claim"),
        embedder.embed("a claim"),
        embedder.name,          # stored under the hashing model
    )
    store.close()

    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(corpus),
            "embed_backend": "ollama",
            "embed_model": "nomic-embed-text",   # ... read back under a different one
            "packs_root": str(PACKS_ROOT),
        }),
        encoding="utf-8",
    )

    code = cli.main(["--config", str(config), "status"])
    output = capsys.readouterr().out

    assert "UNUSABLE" in output, "guard: the condition under test was not provoked"
    assert code != 0, (
        "status printed UNUSABLE and exited 0, so `winnow status && ...` proceeds on a "
        "corpus where every claim would be judged against nothing"
    )


def test_status_still_exits_zero_on_a_healthy_corpus(tmp_path, capsys):
    """The fix must not make the ordinary case look like a failure."""
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "fresh.db"),
            "embed_backend": "hashing",
            "packs_root": str(PACKS_ROOT),
        }),
        encoding="utf-8",
    )
    code = cli.main(["--config", str(config), "status"])
    output = capsys.readouterr().out

    assert "UNUSABLE" not in output
    assert code == 0
