"""A file that exists is a file, whatever its name looks like.

Yesterday's fix taught the CLI to recognise a pasted link with no scheme, so
`youtu.be/dQw4w9WgXcQ` stopped being reported as a missing file. The heuristic matches a
dotted token that looks like a host -- and `README.md` is a dotted token that looks like a
host. So:

    winnow ingest README.md   ->   'README.md' looks like a link with no scheme.
                                   Try https://README.md

on a file that is sitting right there. `talk.txt`, `talk.en.vtt` and `2024.report.md` all do
the same, and `docs/ACQUISITION.md` documents exactly that usage.

My guard test for the original fix used `notes/talk.txt` -- a path WITH a separator, which
the host pattern cannot match. I tested the shape I had in mind rather than the class, which
is the third time in two days.

Two independent corrections here, because either alone leaves a hole:
  - existence is checked FIRST: anything on disk is used, however it is spelled;
  - a name ending in a known transcript/subtitle/media extension is never treated as a
    near-miss link, so a MISTYPED `talk.txt` still reports a missing file rather than
    advising a URL.

Reported by an external review as its most important functional defect.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winnow import cli

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({
            "pack": "ai_tooling",
            "corpus_path": str(tmp_path / "c.db"),
            "embed_backend": "hashing",
            "packs_root": str(PACKS_ROOT),
            "ingest_extra_passes": [],
        }),
        encoding="utf-8",
    )
    return config


@pytest.mark.parametrize(
    "name",
    ["README.md", "talk.txt", "talk.en.vtt", "2024.report.md", "notes.markdown"],
)
def test_an_existing_dotted_file_is_read_not_mistaken_for_a_link(workspace, name, capsys):
    Path(name).write_text(
        "a specific claim about inference throughput on consumer hardware", encoding="utf-8"
    )

    from winnow import pipeline as pipeline_module

    original = pipeline_module.Pipeline.build

    def build(cfg):
        built = original(cfg)
        built.extractor.llm = type(
            "L", (), {"generate": lambda self, m, p, *, num_ctx, as_json=False:
                      json.dumps({"claims": [{"claim": "a claim about throughput"}]})}
        )()
        return built

    pipeline_module.Pipeline.build = staticmethod(build)
    try:
        code = cli.main(["--config", str(workspace), "ingest", name])
    finally:
        pipeline_module.Pipeline.build = staticmethod(original)

    said = "".join(capsys.readouterr())
    assert "https://" + name not in said, (
        f"{name} exists on disk and was reported as a link: {said!r}"
    )
    assert code == 0, f"exit {code}: {said!r}"


@pytest.mark.parametrize("name", ["talk.txt", "missing.en.vtt", "notes.md", "video.mp4"])
def test_a_mistyped_filename_reports_a_missing_file(workspace, name, capsys):
    """Not on disk, but plainly a filename: the answer is 'no such file', not 'try https://'."""
    code = cli.main(["--config", str(workspace), "ingest", name])
    said = "".join(capsys.readouterr()).lower()

    assert code == 2
    assert "no such file" in said, f"{name} is a filename, not a link: {said!r}"
    assert "https://" not in said


@pytest.mark.parametrize(
    "value", ["youtu.be/dQw4w9WgXcQ", "www.youtube.com/watch?v=abc", "youtube.com/watch?v=x"]
)
def test_a_pasted_link_without_a_scheme_still_gets_link_advice(workspace, value, capsys):
    """The guard: yesterday's fix must survive this one."""
    code = cli.main(["--config", str(workspace), "ingest", value])
    said = "".join(capsys.readouterr())

    assert code == 2
    assert "https://" in said, f"a scheme-less link lost its advice: {said!r}"


def test_an_existing_folder_named_like_a_host_is_still_a_folder(workspace, capsys):
    """Folders get dotted names too."""
    folder = Path("archive.2024")
    folder.mkdir()
    (folder / "transcript.txt").write_text("a claim about throughput", encoding="utf-8")

    from winnow import pipeline as pipeline_module

    original = pipeline_module.Pipeline.build

    def build(cfg):
        built = original(cfg)
        built.extractor.llm = type(
            "L", (), {"generate": lambda self, m, p, *, num_ctx, as_json=False:
                      json.dumps({"claims": []})}
        )()
        return built

    pipeline_module.Pipeline.build = staticmethod(build)
    try:
        code = cli.main(["--config", str(workspace), "ingest", str(folder)])
    finally:
        pipeline_module.Pipeline.build = staticmethod(original)

    said = "".join(capsys.readouterr())
    assert "https://archive.2024" not in said, f"an existing folder read as a link: {said!r}"
    assert code == 0


@pytest.mark.parametrize("name", ["talks.co", "archive.io", "corpus.ai"])
def test_an_existing_path_wins_even_with_no_readable_extension(workspace, name, capsys):
    """The case that isolates the ORDERING half of the fix.

    `talks.co` matches the host pattern and its suffix is not in the readable set, so the
    suffix exclusion cannot save it. Only checking existence first does. Written after
    perturbation showed the ordering change had no test that could fail on it: every other
    case here is also caught by the extension rule.
    """
    folder = Path(name)
    folder.mkdir()
    (folder / "transcript.txt").write_text("a claim about throughput", encoding="utf-8")

    from winnow import pipeline as pipeline_module

    original = pipeline_module.Pipeline.build

    def build(cfg):
        built = original(cfg)
        built.extractor.llm = type(
            "L", (), {"generate": lambda self, m, p, *, num_ctx, as_json=False:
                      json.dumps({"claims": []})}
        )()
        return built

    pipeline_module.Pipeline.build = staticmethod(build)
    try:
        code = cli.main(["--config", str(workspace), "ingest", name])
    finally:
        pipeline_module.Pipeline.build = staticmethod(original)

    said = "".join(capsys.readouterr())
    assert f"https://{name}" not in said, (
        f"{name} exists on disk and was answered as a link: {said!r}"
    )
    assert code == 0, f"exit {code}: {said!r}"


def test_the_same_name_not_on_disk_is_treated_as_a_link(workspace, capsys):
    """The mirror, so the ordering fix cannot be satisfied by ignoring links entirely."""
    code = cli.main(["--config", str(workspace), "ingest", "talks.co"])
    said = "".join(capsys.readouterr())

    assert code == 2
    assert "https://talks.co" in said, (
        f"nothing on disk and host-shaped: link advice is right here. Got: {said!r}"
    )
