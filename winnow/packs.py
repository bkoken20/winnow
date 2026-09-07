"""Domain packs -- the only part of Winnow that knows what a subject is about.

A pack is configuration, not code. It carries the claim schema, the prompts, the corpus
thresholds and a starter-source list. Everything else in the codebase is domain-blind,
which is what makes the tool general rather than one tool per field.

Because packs are user configuration, a private pack in any domain can live outside the
repository and never be published.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKS_DIRNAME = "packs"


def _load_json(path: Path):
    """Read JSON, naming the file if it is malformed.

    A bare JSONDecodeError says "line 1 column 2" and nothing else, which is no help at all
    when the tool reads a config file, a pack manifest and a starter-source list.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(f"{path}: {exc.msg}", exc.doc, exc.pos) from None


@dataclass
class Pack:
    name: str
    version: str
    description: str
    schema: dict[str, str]  # field name -> what it means
    extract_prompt: str
    frame_prompt: str = ""
    use_frames: bool = False
    min_corpus: int = 25
    starter_sources: list[dict[str, Any]] = field(default_factory=list)
    path: Path | None = None

    @property
    def schema_fields(self) -> list[str]:
        return list(self.schema.keys())

    def render_extract_prompt(self, text: str) -> str:
        """Placeholder substitution, deliberately not str.format().

        Prompts contain literal JSON braces as examples of the expected output. Passing
        them through str.format() raises KeyError on the first one, so a unique token is
        substituted instead.
        """
        return self.extract_prompt.replace("__TEXT__", text)

    def render_frame_prompt(self) -> str:
        return self.frame_prompt


def load_pack(directory: Path) -> Pack:
    directory = Path(directory)
    manifest_path = directory / "pack.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no pack.json in {directory}")
    manifest = _load_json(manifest_path)

    def _read(key: str, default: str = "") -> str:
        filename = manifest.get(key)
        if not filename:
            return default
        return (directory / filename).read_text(encoding="utf-8")

    starter = []
    starter_file = manifest.get("starter_sources")
    if starter_file and (directory / starter_file).exists():
        starter = _load_json(directory / starter_file)

    return Pack(
        name=manifest["name"],
        version=str(manifest.get("version", "1")),
        description=manifest.get("description", ""),
        schema=manifest.get("schema", {}),
        extract_prompt=_read("extract_prompt"),
        frame_prompt=_read("frame_prompt"),
        use_frames=bool(manifest.get("use_frames", False)),
        min_corpus=int(manifest.get("min_corpus", 25)),
        starter_sources=starter,
        path=directory,
    )


def packs_root(explicit: Path | None = None) -> Path:
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parent.parent / PACKS_DIRNAME


def available_packs(root: Path | None = None) -> list[str]:
    base = packs_root(root)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "pack.json").exists())


def find_pack(name: str, root: Path | None = None) -> Pack:
    base = packs_root(root)
    directory = base / name
    if not (directory / "pack.json").exists():
        raise FileNotFoundError(
            f"pack {name!r} not found in {base}. Available: {', '.join(available_packs(root)) or 'none'}"
        )
    return load_pack(directory)
