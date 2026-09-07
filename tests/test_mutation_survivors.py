"""Gaps found by mutation sampling, not by reading.

A uniform random sample of 30 mutations to `winnow/*.py` was applied one at a time and the
suite re-run. 14 died. Of the 16 that lived, most were equivalent mutants -- `flush=True`
made False, a 600-second timeout made 601, a JSON indent widened -- which change no
behaviour any test could legitimately observe.

Four were real. One (the judge stamp) belonged in `test_judge.py` beside its neighbours. The
rest are here, with the mutation that survived recorded against each, so a later reader can
re-apply it rather than trusting this note.

Reading the tests told me what they intended to check. Only this told me what they caught.
"""
from __future__ import annotations


import pytest

from winnow.config import Config
from winnow.cost import Projection, accepted_by_flag

# -- resolved_notes_path -------------------------------------------------------------
#
# SURVIVED: `self.notes_path or os.environ.get(...)` with `or` flipped to `and`.
#
# Nothing at all exercised this method, and two commands depend on it: `winnow status`
# prints it, and `winnow index` with no folder argument uses it as the folder to index.
# Under the mutation, a configured notes_path is discarded in favour of an unset
# environment variable, so `winnow index` indexes nothing and says nothing.


@pytest.fixture
def no_notes_env(monkeypatch):
    monkeypatch.delenv("WINNOW_NOTES", raising=False)


def test_configured_notes_path_is_used(no_notes_env, tmp_path):
    config = Config(pack="ai_tooling", notes_path=str(tmp_path / "mynotes"))
    assert config.resolved_notes_path() == tmp_path / "mynotes"


def test_the_environment_supplies_it_when_the_config_does_not(monkeypatch, tmp_path):
    monkeypatch.setenv("WINNOW_NOTES", str(tmp_path / "envnotes"))
    config = Config(pack="ai_tooling", notes_path="")
    assert config.resolved_notes_path() == tmp_path / "envnotes"


def test_the_config_wins_over_the_environment(monkeypatch, tmp_path):
    """Explicit configuration beats ambient state, which is the point of having both."""
    monkeypatch.setenv("WINNOW_NOTES", str(tmp_path / "envnotes"))
    config = Config(pack="ai_tooling", notes_path=str(tmp_path / "confignotes"))
    assert config.resolved_notes_path() == tmp_path / "confignotes"


def test_neither_set_is_none_not_an_empty_path(no_notes_env):
    """`Path("")` is the current directory, so returning one would index the whole tree."""
    assert Config(pack="ai_tooling", notes_path="").resolved_notes_path() is None


# -- the accepted budget -------------------------------------------------------------
#
# SURVIVED: `accept_minutes * 60` with 60 made 61.
#
# The gate's whole contract is that you accept a number you were shown. Nothing pinned the
# conversion, so the accepted budget could drift from the minutes the user actually typed
# and still pass -- the failure being silent and always in the permissive direction.


def test_an_accepted_budget_means_exactly_that_many_minutes():
    ten_minutes = Projection(unit_seconds=1.0, units=600)
    assert ten_minutes.total_seconds == pytest.approx(600)

    assert accepted_by_flag(10, ten_minutes) is True, "10 minutes must cover 600 seconds"
    assert accepted_by_flag(9.99, ten_minutes) is False, (
        "a budget short of the projection must not pass; 60 seconds to the minute, "
        "not 61 -- the drift would always be in the permissive direction"
    )


def test_no_budget_is_not_an_unlimited_budget():
    assert accepted_by_flag(None, Projection(unit_seconds=1.0, units=1)) is False


# -- the refusal must name a budget that works ---------------------------------------
#
# Not from mutation sampling: found reading cost.py. `:.0f` rounds to nearest, so a
# 130-second run is refused with "Re-run with --accept-minutes 2", and 2 minutes is 120
# seconds, which does not cover it. Following the tool's own instruction fails identically.


def _suggested_budget(projection) -> float:
    import re

    from winnow.cost import RunRefused, gate

    try:
        gate(projection, accepted=False)
    except RunRefused as exc:
        return float(re.search(r"--accept-minutes ([0-9.]+)", str(exc)).group(1))
    raise AssertionError("expected the run to be refused")


@pytest.mark.parametrize(
    "unit_seconds,units",
    [
        (1.3, 100),      # 130 s -> the original failure
        (1.0, 121),      # just over the threshold
        (0.001, 200000), # 200 s
        (7.0, 1000),     # 7000 s, into hours
        (1.0, 3661),     # an hour and a second
    ],
)
def test_the_budget_the_refusal_names_is_actually_accepted(unit_seconds, units, capsys):
    projection = Projection(unit_seconds=unit_seconds, units=units)
    suggested = _suggested_budget(projection)
    capsys.readouterr()
    assert accepted_by_flag(suggested, projection), (
        f"refusal suggested --accept-minutes {suggested}, which is "
        f"{suggested * 60:.1f}s, and the run needs {projection.total_seconds:.1f}s. "
        "Following the tool's own instruction is refused again."
    )


def test_the_suggested_budget_is_not_wastefully_larger_than_needed(capsys):
    """Rounding up must not become rounding up to the next hour."""
    projection = Projection(unit_seconds=1.3, units=100)  # 130 s
    suggested = _suggested_budget(projection)
    capsys.readouterr()
    assert suggested * 60 < projection.total_seconds + 60, (
        f"suggested {suggested} minutes for a {projection.total_seconds}s run"
    )
