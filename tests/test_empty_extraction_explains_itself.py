"""Zero claims must explain itself, or the tool reads as broken on its first real use.

Found by pointing the shipped configuration at a real video that was not about AI tooling.
Winnow fetched the captions, ran ten chunks through the extractor, and printed:

    0 claims extracted

That is the CORRECT answer. The `ai_tooling` pack asks for "factual claims about AI and
local-LLM tooling"; the video was about chart analysis, so the model returned `{"claims": []}`
for every chunk, exactly as the prompt instructs it to. Nothing was broken.

But nothing said so. The default pack is domain-specific and most people's first video will
not be about that domain, so this is the single most likely first-run experience for a
stranger -- and what they see is a tool that took their link, thought about it, and produced
nothing at all. They conclude it is broken and say so publicly.

A right answer given without its reason is indistinguishable from a failure.
"""
from __future__ import annotations

import json
from pathlib import Path

from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class NothingFoundLLM:
    """What a domain-specific extractor really returns on out-of-domain material."""

    def generate(self, model, prompt, *, num_ctx, as_json=False):
        return '{"claims": []}'


def _configured(tmp_path) -> Path:
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "corpus.db"),
            "embed_backend": "hashing",
            "packs_root": str(PACKS_ROOT),
        }),
        encoding="utf-8",
    )
    folder = tmp_path / "talk"
    folder.mkdir()
    (folder / "transcript.txt").write_text(
        "a long discussion of something entirely outside this pack's subject " * 40,
        encoding="utf-8",
    )
    return config


def test_zero_claims_names_the_pack_and_what_it_looks_for(tmp_path, capsys, monkeypatch):
    from winnow import pipeline as pipeline_module

    original_build = pipeline_module.Pipeline.build

    def build_with_stub_llm(config):
        built = original_build(config)
        built.extractor.llm = NothingFoundLLM()
        return built

    monkeypatch.setattr(pipeline_module.Pipeline, "build", staticmethod(build_with_stub_llm))

    config = _configured(tmp_path)
    code = cli.main(["--config", str(config), "ingest", str(tmp_path / "talk")])
    said = capsys.readouterr()
    output = (said.out + said.err).lower()

    assert code == 0, "finding nothing is an answer, not an error"
    assert "0 claims" in output
    assert "ai_tooling" in output, (
        "the reader has to be told WHICH pack found nothing; the default one is "
        f"domain-specific. Output was: {output!r}"
    )
    assert "domain_packs" in output or "pack for" in output, (
        "and where to go if their material is about something else"
    )


def test_a_normal_run_does_not_carry_the_explanation(tmp_path, capsys, monkeypatch):
    """The message must appear only when nothing was found."""
    from winnow import pipeline as pipeline_module

    original_build = pipeline_module.Pipeline.build

    class OneClaimLLM:
        def generate(self, model, prompt, *, num_ctx, as_json=False):
            return '{"claims": [{"claim": "a specific measurable assertion about tooling"}]}'

    def build_with_stub_llm(config):
        built = original_build(config)
        built.extractor.llm = OneClaimLLM()
        return built

    monkeypatch.setattr(pipeline_module.Pipeline, "build", staticmethod(build_with_stub_llm))

    config = _configured(tmp_path)
    cli.main(["--config", str(config), "ingest", str(tmp_path / "talk")])
    output = capsys.readouterr().out.lower()

    # "0 claims" occurs legitimately in a thin-corpus rationale ("corpus holds 0 claims
    # for pack ..."), so assert the absence of the EXPLANATION rather than of a substring
    # that has other reasons to appear.
    assert "1 claims" in output
    assert "domain_packs" not in output
    assert "looks for" not in output
