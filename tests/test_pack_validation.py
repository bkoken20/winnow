"""A pack that would silently produce nonsense must be refused at load time.

An extraction prompt without `__TEXT__` loaded without complaint and sent the model a
prompt containing no source material at all. The model then invents claims or returns
nothing, and there is no error anywhere -- the extraction simply looks unproductive.
`docs/DOMAIN_PACKS.md` said the token was required. Nothing enforced it.

Authoring a pack is the tool's whole extensibility story, so a trap there is worth more
than a trap in the core: it is hit by the people least able to diagnose it.
"""

import json
from pathlib import Path

import pytest

from winnow.packs import TEXT_TOKEN, InvalidPack, find_pack, load_pack

REPO_PACKS = Path(__file__).resolve().parent.parent / "packs"


def write_pack(tmp_path, *, prompt="Find claims in:\n__TEXT__\n", frame=None, **manifest):
    directory = tmp_path / "packs" / manifest.get("name", "testpack")
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"name": "testpack", "version": "1", "extract_prompt": "extract.txt"}
    payload.update(manifest)
    if prompt is not None:
        (directory / "extract.txt").write_text(prompt, encoding="utf-8")
    if frame is not None:
        (directory / "frame.txt").write_text(frame, encoding="utf-8")
        payload["frame_prompt"] = "frame.txt"
    (directory / "pack.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def test_a_prompt_without_the_text_token_is_refused(tmp_path):
    """The defect: the source never reaches the model, and nothing says so."""
    directory = write_pack(tmp_path, prompt="Find all the claims. Return JSON.")

    with pytest.raises(InvalidPack) as exc:
        load_pack(directory)

    message = str(exc.value)
    assert TEXT_TOKEN in message, "the message must name the missing token"
    assert "extract.txt" in message, "and the file to fix"
    assert "invent" in message, "and what goes wrong if it is not fixed"


def test_an_empty_prompt_is_refused(tmp_path):
    directory = write_pack(tmp_path, prompt="   \n\n  ")
    with pytest.raises(InvalidPack):
        load_pack(directory)


def test_a_missing_prompt_file_reference_is_refused(tmp_path):
    directory = write_pack(tmp_path, prompt=None, extract_prompt=None)
    with pytest.raises(InvalidPack):
        load_pack(directory)


def test_use_frames_without_a_frame_prompt_is_refused(tmp_path):
    """Frames would be sampled, described with an empty prompt, and wasted."""
    directory = write_pack(tmp_path, use_frames=True)
    with pytest.raises(InvalidPack) as exc:
        load_pack(directory)
    assert "use_frames" in str(exc.value)


def test_use_frames_with_a_frame_prompt_is_fine(tmp_path):
    directory = write_pack(tmp_path, use_frames=True, frame="Describe the frame.")
    pack = load_pack(directory)
    assert pack.use_frames


def test_a_pack_without_frames_needs_no_frame_prompt(tmp_path):
    pack = load_pack(write_pack(tmp_path))
    assert not pack.use_frames
    assert pack.frame_prompt == ""


def test_the_shipped_pack_passes_its_own_validation():
    """The rule must be one the reference pack actually satisfies."""
    pack = find_pack("ai_tooling", REPO_PACKS)
    assert TEXT_TOKEN in pack.extract_prompt
    assert pack.use_frames and pack.frame_prompt.strip()


def test_the_validator_and_the_renderer_use_the_same_token(tmp_path):
    """A validator checking a different token than the renderer substitutes would pass
    every broken pack while changing nothing."""
    pack = load_pack(write_pack(tmp_path))
    rendered = pack.render_extract_prompt("THE SOURCE MATERIAL")
    assert "THE SOURCE MATERIAL" in rendered
    assert TEXT_TOKEN not in rendered


def test_the_cli_reports_an_invalid_pack_without_a_traceback(tmp_path, capsys):
    from winnow import cli

    write_pack(tmp_path, name="broken", prompt="No token here.")
    config = tmp_path / "winnow.json"
    config.write_text(
        json.dumps({"pack": "broken", "packs_root": str(tmp_path / "packs")}), encoding="utf-8"
    )

    code = cli.main(["--config", str(config), "packs"])
    err = capsys.readouterr().err
    assert code != 0
    assert "Traceback" not in err
    assert TEXT_TOKEN in err
