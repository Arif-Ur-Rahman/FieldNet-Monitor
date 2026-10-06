"""Background work: run everything that has fallen due, in due-time order.

Engine modules register due-work sources. A source is a function
`next_due(up_to) -> Due | None` returning its earliest item due at or before
`up_to`. tick() keeps taking the earliest item across all sources and runs it,
each in its own transaction, until nothing is due. Running an item must make it
no longer due (or due later), otherwise tick() stops at MAX_STEPS.

Each item runs with its own due time as `effective_at`, never the time tick()
was called with: a clock jump from day 1 to day 5 applies a day-3 timer at day 3.
Items due at the same instant run in source order: lower `order` first, then
registration order. Evidence comes before timers: batches (10), gateways (20),
sensors (30).

The worker calls tick(clock.now()) every few seconds. In TEST_MODE background
work never runs on its own: only /test/clock and /test/drain call tick().
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

log = logging.getLogger(__name__)

MAX_STEPS = 100_000


@dataclass(frozen=True)
class Due:
    due_at: datetime
    run: Callable[[datetime], None]  # called with effective_at = due_at
    label: str = ""


Source = Callable[[datetime], Due | None]

BATCHES, GATEWAYS, SENSORS = 10, 20, 30

_sources: list[tuple[int, str, Source]] = []


def register(name: str, source: Source, *, order: int = 100) -> None:
    """Add a source. Registering the same name again replaces it."""
    unregister(name)
    _sources.append((order, name, source))
    # Stable sort: equal orders keep registration order.
    _sources.sort(key=lambda s: s[0])


def unregister(name: str) -> None:
    _sources[:] = [s for s in _sources if s[1] != name]


def _next(up_to: datetime) -> Due | None:
    best = None
    for _, _, source in _sources:
        due = source(up_to)
        # Strictly earlier wins, so equal due times keep registration order.
        if due is not None and (best is None or due.due_at < best.due_at):
            best = due
    return best


def tick(now: datetime) -> int:
    """Run every item due at or before `now`. Returns how many ran."""
    for steps in range(MAX_STEPS):
        due = _next(now)
        if due is None:
            return steps
        with transaction.atomic():
            due.run(due.due_at)
    log.error("tick(%s) stopped after %d steps; a source keeps returning due work", now.isoformat(), MAX_STEPS)
    return MAX_STEPS
