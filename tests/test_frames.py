"""Frame description, wired into ingest.

This path was documented in the README, configured in the pack (`use_frames: true`),
covered by unit tests, and never called by anything: `extract_frames`, `describe_image` and
`render_frame_prompt` had no caller, and `vision_model` was read by nothing. Media sitting
beside a transcript was used for nothing at all.

Tests below cover the wiring, not ffmpeg -- frame extraction itself is stubbed, because
whether ffmpeg works is not what was broken.
"""

import json
from pathlib import Path

from winnow.config import Config
from winnow.extract import Extractor
from winnow.media import Frame
from winnow.pipeline import Pipeline

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


class EchoExtractLLM:
    """Turns whatever it is given into one claim, so tests can see what reached it."""

    def __init__(self):
        self.seen = []
        self.vision_calls = []

    def generate(self, model, prompt, *, num_ctx, as_json=False, images=None):
        self.seen.append(prompt)
        return json.dumps({"claims": [{"claim": "a claim"}]})

    def describe_image(self, model, prompt, image_b64, *, num_ctx):
        self.vision_calls.append({"model": model, "prompt": prompt, "num_ctx": num_ctx})
        return "a terminal showing 42 tokens per second"


def build(tmp_path, llm, monkeypatch, frames=None, **overrides) -> Pipeline:
    config = Config(
        pack="ai_tooling",
        corpus_path=str(tmp_path / "corpus.db"),
        embed_backend="hashing",
        packs_root=str(PACKS_ROOT),
        ingest_extra_passes=[],
        **overrides,
    )
    pipeline = Pipeline.build(config)
    pipeline.extractor = Extractor(llm=llm, model="fake", num_ctx=32768, pack=pipeline.pack)
    pipeline.llm = llm
    if frames is not None:
        monkeypatch.setattr("winnow.pipeline.extract_frames", lambda *a, **k: frames)
    return pipeline


def material(tmp_path, with_media: bool) -> Path:
    folder = tmp_path / "talk"
    folder.mkdir(exist_ok=True)
    (folder / "transcript.txt").write_text("the speaker says something", encoding="utf-8")
    if with_media:
        (folder / "video.mp4").write_bytes(b"\x00\x00")
    return folder


def fake_frame(tmp_path, index=0) -> Frame:
    path = tmp_path / f"f{index}.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0jpegish")
    return Frame(index=index, seconds=index * 30, path=path)


def test_pack_with_use_frames_actually_describes_frames(tmp_path, monkeypatch):
    """The regression: nothing ever called the vision path."""
    llm = EchoExtractLLM()
    pipeline = build(tmp_path, llm, monkeypatch, frames=[fake_frame(tmp_path)])
    assert pipeline.pack.use_frames

    pipeline.ingest(material(tmp_path, with_media=True))

    assert llm.vision_calls, "use_frames is true and media is present; no frame was described"
    assert llm.vision_calls[0]["model"] == pipeline.config.vision_model
    assert llm.vision_calls[0]["num_ctx"] == pipeline.config.vision_num_ctx
    pipeline.close()


def test_frame_descriptions_reach_the_extractor(tmp_path, monkeypatch):
    """Describing frames is pointless unless the description informs extraction."""
    llm = EchoExtractLLM()
    pipeline = build(tmp_path, llm, monkeypatch, frames=[fake_frame(tmp_path)])
    pipeline.ingest(material(tmp_path, with_media=True))

    combined = "\n".join(llm.seen)
    assert "42 tokens per second" in combined
    assert "the speaker says something" in combined  # transcript still present
    pipeline.close()


def test_no_media_means_no_vision_calls(tmp_path, monkeypatch):
    llm = EchoExtractLLM()
    pipeline = build(tmp_path, llm, monkeypatch, frames=[fake_frame(tmp_path)])
    pipeline.ingest(material(tmp_path, with_media=False))
    assert llm.vision_calls == []
    pipeline.close()


def test_missing_ffmpeg_does_not_fail_the_ingest(tmp_path, monkeypatch):
    """A transcript already in hand must not be lost because the optional half is absent."""
    from winnow.media import FFmpegMissing

    def boom(*a, **k):
        raise FFmpegMissing("ffmpeg not found")

    llm = EchoExtractLLM()
    pipeline = build(tmp_path, llm, monkeypatch)
    monkeypatch.setattr("winnow.pipeline.extract_frames", boom)

    claims, _ = pipeline.ingest(material(tmp_path, with_media=True))
    assert claims, "ingest should have succeeded on the transcript alone"
    assert llm.vision_calls == []
    pipeline.close()


def test_a_vision_model_error_skips_that_frame_only(tmp_path, monkeypatch):
    from winnow.llm import OllamaError

    class HalfBrokenLLM(EchoExtractLLM):
        def describe_image(self, model, prompt, image_b64, *, num_ctx):
            self.vision_calls.append(model)
            if len(self.vision_calls) == 1:
                raise OllamaError("model unavailable")
            return "a chart showing throughput"

    llm = HalfBrokenLLM()
    frames = [fake_frame(tmp_path, 0), fake_frame(tmp_path, 1)]
    pipeline = build(tmp_path, llm, monkeypatch, frames=frames)
    pipeline.ingest(material(tmp_path, with_media=True))

    assert len(llm.vision_calls) == 2
    assert "throughput" in "\n".join(llm.seen)
    pipeline.close()


def test_ingest_writes_nothing_into_the_user_s_folder(tmp_path, monkeypatch):
    """Winnow reads what it is pointed at. It does not leave files there.

    Frame extraction originally wrote JPEGs into the source folder: a side effect nobody
    asked for, which fails outright on read-only or shared storage and leaves litter behind
    after every ingest. Frames belong in a temporary directory.
    """
    llm = EchoExtractLLM()
    folder = material(tmp_path, with_media=True)
    before = {p.name for p in folder.iterdir()}

    # The real extractor, not a stub -- the point is where files land, and a stub that
    # returns frames without writing them could not detect this.
    pipeline = build(tmp_path, llm, monkeypatch)
    captured = {}

    def fake_ffmpeg(media, out_dir, every_seconds=30, limit=40, **kwargs):
        captured["out_dir"] = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        jpeg = out_dir / "frame_00001.jpg"
        jpeg.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        return [Frame(index=0, seconds=0, path=jpeg)]

    monkeypatch.setattr("winnow.pipeline.extract_frames", fake_ffmpeg)
    pipeline.ingest(folder)

    assert {p.name for p in folder.iterdir()} == before, (
        f"ingest left files behind in the source folder: "
        f"{ {p.name for p in folder.iterdir()} - before }"
    )
    assert folder not in captured["out_dir"].parents, (
        f"frames were extracted into the user's folder ({captured['out_dir']})"
    )
    pipeline.close()


def test_frame_sampling_honours_the_configured_limits(tmp_path, monkeypatch):
    """One vision call per frame on a path with no cost gate -- the limits must apply."""
    llm = EchoExtractLLM()
    pipeline = build(tmp_path, llm, monkeypatch, frame_every_seconds=90, max_frames=5)
    seen = {}

    def fake_ffmpeg(media, out_dir, every_seconds=30, limit=40, **kwargs):
        seen.update(every_seconds=every_seconds, limit=limit)
        return []

    monkeypatch.setattr("winnow.pipeline.extract_frames", fake_ffmpeg)
    pipeline.ingest(material(tmp_path, with_media=True))

    assert seen == {"every_seconds": 90, "limit": 5}
    pipeline.close()


def test_packs_without_use_frames_never_touch_video(tmp_path, monkeypatch):
    llm = EchoExtractLLM()
    pipeline = build(tmp_path, llm, monkeypatch, frames=[fake_frame(tmp_path)])
    pipeline.pack.use_frames = False
    pipeline.ingest(material(tmp_path, with_media=True))
    assert llm.vision_calls == []
    pipeline.close()
