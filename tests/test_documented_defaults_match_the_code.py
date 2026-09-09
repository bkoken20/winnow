"""Every default printed in the parameters table must be the default in the code.

`docs/PARAMETERS.md` documented `caption_languages` as `en.*` after the code moved to
`en-orig` -- and `docs/ACQUISITION.md` went on recommending `--sub-langs "en.*"` in four
worked examples while, further down the same page, explaining that this exact pattern
downloaded every caption twice and earned a rate limit.

Reported by an external review. Both are mine, from the fix that changed the default.

The existing documentation tests check that every setting is MENTIONED. Mentioning it is
what kept this green: the row was there, with the wrong value in it. This checks the value.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from winnow.config import Config

ROOT = Path(__file__).resolve().parent.parent
PARAMETERS = (ROOT / "docs" / "PARAMETERS.md").read_text(encoding="utf-8")
ACQUISITION = (ROOT / "docs" / "ACQUISITION.md").read_text(encoding="utf-8")

# `| `name` | `value` | description |` -- the shape every settings row uses.
_ROW = re.compile(r"^\| `([a-z_][a-z0-9_]*)` \| `([^`]+)` \|", re.MULTILINE)


def _documented_defaults() -> dict[str, str]:
    return {name: value for name, value in _ROW.findall(PARAMETERS)}


def _actual_defaults() -> dict[str, str]:
    out = {}
    for field in dataclasses.fields(Config):
        if field.default is not dataclasses.MISSING:
            out[field.name] = field.default
        elif field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            out[field.name] = field.default_factory()  # type: ignore[misc]
    return out


def test_the_table_documents_some_defaults():
    """Guard the guard: a regex that stops matching would pass everything below."""
    assert len(_documented_defaults()) >= 10, (
        f"only parsed {len(_documented_defaults())} rows from PARAMETERS.md"
    )


@pytest.mark.parametrize("setting", sorted(_documented_defaults()))
def test_each_documented_default_is_the_real_one(setting):
    documented = _documented_defaults()[setting]
    actual = _actual_defaults()

    if setting not in actual:
        pytest.skip(f"{setting} is not a Config field")

    rendered = {
        "": "*(empty)*",
    }.get(str(actual[setting]), str(actual[setting]))

    assert documented == rendered, (
        f"docs/PARAMETERS.md says `{setting}` defaults to `{documented}`; the code says "
        f"`{rendered}`. A reader tuning from the page is tuning from a value that is not "
        "what they have."
    )


def test_the_acquisition_page_does_not_recommend_the_pattern_it_warns_about():
    """It recommended `en.*` four times and explained on the same page why not to use it."""
    warns = "matched both tracks" in ACQUISITION or "downloaded" in ACQUISITION
    assert warns, "guard: the warning this test pairs with has gone"

    # Match the RECOMMENDATION form -- the pattern used as an actual flag value -- not any
    # mention of it. The first version matched the substring and was tripped by this page's
    # own explanation of why not to use it, which is the "grep matches my own prose" trap.
    recommendations = [
        line for line in ACQUISITION.splitlines() if '--sub-langs "en.*"' in line
    ]
    assert not recommendations, (
        "these lines still recommend the caption pattern the same page says caused "
        "duplicate downloads and a rate limit:\n  " + "\n  ".join(recommendations)
    )
