"""A pack's "nothing here" reply only works if it is UPPERCASE, and nothing says so.

`_describe_each` drops a frame description when `text.strip("`\\"' .").isupper()`. That is a
generic rule, deliberately: the pack chooses its own token rather than the code hard-coding
one. But the rule it actually applies is "all upper case", and docs/DOMAIN_PACKS.md shows
NO_TECHNICAL_CONTENT as an example without ever saying that the capitals are what makes it
work.

A pack author who follows that advice with "nothing here", or "No technical content", gets
the sentinel stored as a frame description and appended to the transcript under
[ON-SCREEN CONTENT], where the extractor reads it as something that was actually on screen.
Silent, and it degrades exactly the material frames exist to improve.

packs.py puts it best: a trap in pack authoring is worth more than a trap in the core,
because it is hit by the people least able to diagnose it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from winnow.config import Config
from winnow.media import Frame

ROOT = Path(__file__).resolve().parent.parent


class StubFrame(Frame):
    def to_base64(self) -> str:  # never reads a file
        return ""


def _pipeline_with(reply: str, tmp_path):
    """A Pipeline whose vision model always answers `reply`."""
    from winnow.pipeline import Pipeline

    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "c.db"),
        embed_backend="hashing",
    )
    pipeline = Pipeline.build(config)

    class FixedVision:
        def describe_image(self, model, prompt, image_b64, *, num_ctx):
            return reply

    pipeline.llm = FixedVision()
    return pipeline


@pytest.mark.parametrize(
    "reply,kept",
    [
        ("NO_TECHNICAL_CONTENT", False),   # the shipped pack's token
        ("NOTHING HERE", False),
        ("no technical content", True),    # a lower-case sentinel is NOT filtered
        ("Nothing here", True),
        ("A terminal shows 24 tokens per second.", True),
    ],
)
def test_only_an_uppercase_sentinel_is_filtered(reply, kept, tmp_path):
    """Pins the rule as it actually is, so the docs can describe something true."""
    pipeline = _pipeline_with(reply, tmp_path)
    try:
        described = pipeline._describe_each(
            [StubFrame(index=0, seconds=0, path=tmp_path / "f.jpg")], "prompt"
        )
    finally:
        pipeline.close()
    assert bool(described) is kept, f"{reply!r} -> {described!r}"


def test_the_shipped_pack_uses_a_sentinel_that_is_actually_filtered(tmp_path):
    from winnow.packs import find_pack

    prompt = find_pack("ai_tooling").frame_prompt
    sentinels = [
        line.strip() for line in prompt.splitlines()
        if line.strip() and line.strip() == line.strip().upper() and len(line.strip()) > 3
    ]
    assert sentinels, "the shipped frame prompt declares no escape token"
    for sentinel in sentinels:
        pipeline = _pipeline_with(sentinel, tmp_path)
        try:
            described = pipeline._describe_each(
                [StubFrame(index=0, seconds=0, path=tmp_path / "f.jpg")], "prompt"
            )
        finally:
            pipeline.close()
        assert not described, f"the pack's own sentinel {sentinel!r} would be stored"


def test_the_pack_guide_says_the_sentinel_must_be_uppercase():
    guide = (ROOT / "docs" / "DOMAIN_PACKS.md").read_text(encoding="utf-8")
    section = guide.split("## The frame prompt")[1].split("## ")[0].lower()
    assert "upper" in section or "capital" in section, (
        "the guide shows NO_TECHNICAL_CONTENT as the escape token but never says the "
        "capitals are what makes it work; a lower-case sentinel is stored as a real "
        "description and fed to the extractor as on-screen content"
    )
