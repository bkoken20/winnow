"""Measure one unit, project the whole run, and only then start.

Indexing a notes folder is one model call per chunk, a few seconds each. A few hundred
files is a coffee break; a few thousand is an afternoon; ten thousand is overnight. The
difference matters enough that it must never be discovered halfway through.

So: process one real unit, time it on the wall clock, multiply, print the projection, and
require acceptance before continuing. There is no flag that skips the measurement -- the
only way past it is to be shown a number and accept it.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Projection:
    """A projected run cost.

    `units` are files when work scales with file count, but extraction time actually scales
    with how much TEXT there is, and real folders are wildly uneven -- in the corpus this
    was first run against, files ranged from 24 bytes to 91 KB, an 18x spread around the
    median. Measuring one file and multiplying by the file count therefore produces a
    number that can be out by an order of magnitude in either direction, depending on
    whether the sampled file happened to be a stub or a monster.

    So when byte counts are available, projection is done on total volume instead: measure
    throughput (bytes per second) on the sampled file, and scale by the folder's real size.
    `units` is retained for reporting and for the file-count case.
    """

    unit_seconds: float
    units: int
    sample_bytes: int = 0
    total_bytes: int = 0

    # De-duplication compares each new claim against every claim already stored, so its
    # cost per claim grows linearly with the corpus and the run's TOTAL dedupe cost grows
    # quadratically. Measuring the first file -- against a corpus that is at its smallest --
    # therefore under-reports precisely the large runs this gate exists to protect against.
    #
    # Measured: one scan is ~0.039 ms per stored claim, so at 10,000 claims a single
    # insert spends ~390 ms scanning before any model is called.
    scan_seconds_per_claim: float = 0.0  # cost of one scan, per claim already stored
    # What the sampled unit actually took, before its own scan time was subtracted out.
    # Kept so the subtraction is observable: `unit_seconds` is extraction only, and the
    # difference between the two is the sample's de-duplication scanning.
    measured_unit_seconds: float = 0.0
    corpus_claims_at_start: int = 0
    expected_new_claims: int = 0

    @property
    def scales_by_volume(self) -> bool:
        return self.sample_bytes > 0 and self.total_bytes > 0

    @property
    def extraction_seconds(self) -> float:
        if self.scales_by_volume:
            bytes_per_second = self.sample_bytes / max(self.unit_seconds, 1e-9)
            return self.total_bytes / bytes_per_second
        return self.unit_seconds * self.units

    @property
    def dedupe_seconds(self) -> float:
        """Total scanning across the run.

        Claim i is compared against `start + i` existing claims, so the sum over n new
        claims is k * (n * start + n^2 / 2).
        """
        if self.scan_seconds_per_claim <= 0 or self.expected_new_claims <= 0:
            return 0.0
        n = self.expected_new_claims
        return self.scan_seconds_per_claim * (
            n * self.corpus_claims_at_start + (n * n) / 2
        )

    @property
    def total_seconds(self) -> float:
        return self.extraction_seconds + self.dedupe_seconds

    def human(self) -> str:
        total = self.total_seconds
        if total < 90:
            return f"{total:.0f} seconds"
        if total < 5400:
            return f"{total / 60:.1f} minutes"
        return f"{total / 3600:.1f} hours"

    def describe(self) -> str:
        if self.scales_by_volume:
            rate = self.sample_bytes / max(self.unit_seconds, 1e-9)
            base = (
                f"measured {self.unit_seconds:.2f}s for {self.sample_bytes / 1024:.1f} KB "
                f"({rate / 1024:.1f} KB/s); {self.units} files totalling "
                f"{self.total_bytes / 1e6:.1f} MB"
            )
        else:
            base = f"measured {self.unit_seconds:.2f}s for one unit x {self.units} units"

        if self.dedupe_seconds > 0:
            base += (
                f"; plus de-duplication scanning over a corpus growing from "
                f"{self.corpus_claims_at_start:,} to about "
                f"{self.corpus_claims_at_start + self.expected_new_claims:,} claims "
                f"({self.dedupe_seconds / 60:.1f} min)"
            )
        return base + f" = about {self.human()}"


class RunRefused(RuntimeError):
    """Raised when a projected run was not accepted."""


def time_one(callable_, *args, **kwargs) -> tuple[object, float]:
    start = time.perf_counter()
    result = callable_(*args, **kwargs)
    return result, time.perf_counter() - start


def gate(projection: Projection, accepted: bool, *, threshold_seconds: float = 120.0) -> None:
    """Allow a run to proceed, or refuse it.

    Runs shorter than the threshold proceed without ceremony -- a gate that fires on a
    twenty-second job trains people to click through it, which defeats the purpose.

    Above the threshold the projection is ALWAYS announced, whether or not the run was
    pre-accepted. Acceptance previously silenced it entirely, so `--accept-minutes 999999`
    started a 1,389-hour run without the user ever seeing a number -- while the
    documentation promised the tool "shows you the number, and waits for you to accept it".
    A budget accepted sight-unseen is not informed consent, and a projection nobody reads
    is not a measurement anyone benefits from.

    Announced on stderr: this is a library, and a caller parsing stdout should not have to
    contend with progress chatter.
    """
    if projection.total_seconds <= threshold_seconds:
        return

    print(f"projected run: {projection.describe()}", file=sys.stderr, flush=True)

    if accepted:
        print(
            f"proceeding -- accepted budget covers {projection.human()}",
            file=sys.stderr,
            flush=True,
        )
        return
    raise RunRefused(
        f"This run is projected at {projection.human()} ({projection.describe()}).\n"
        f"Re-run with --accept-minutes {suggested_budget_minutes(projection)} to proceed."
    )


def suggested_budget_minutes(projection: Projection) -> int:
    """The smallest whole minute figure that `accepted_by_flag` will actually accept.

    Rounded UP, not to nearest. `:.0f` turned a 130-second run into "--accept-minutes 2",
    and two minutes is 120 seconds, so the user followed the instruction the tool had just
    given them and was refused again with the same message. An instruction that does not
    work when obeyed is worse than no instruction.
    """
    return math.ceil(projection.total_seconds / 60)


def accepted_by_flag(accept_minutes: float | None, projection: Projection) -> bool:
    """True when the user's accepted budget covers the projection they were shown."""
    if accept_minutes is None:
        return False
    return accept_minutes * 60 >= projection.total_seconds
