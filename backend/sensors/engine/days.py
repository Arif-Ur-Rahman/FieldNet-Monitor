"""Classify a sensor's complete UTC days (the brief's "Sensor days").

First match wins:
  reading     an accepted reading was taken that day, from any gateway
  unresolved  a readings outcome that day points to a batch not yet resolved
  quiet       a no_readings outcome that day from a gateway whose coverage
              class was available at the cycle's finished_at
  unchecked   everything else: could_not_read, timed_out, silence

A batch resolves when it ends processed, partially_processed or quarantined,
or when the batch deadline (24h) passes after the cycle's finished_at without
it arriving. A missing or quarantined batch turns its outcome into
could_not_read. Classification uses what is known at `now`.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

READING = "reading"
UNRESOLVED = "unresolved"
QUIET = "quiet"
UNCHECKED = "unchecked"


@dataclass(frozen=True)
class Outcome:
    """One recorded cycle outcome for the sensor."""

    gateway_id: str
    finished_at: datetime
    outcome: str  # readings | no_readings | could_not_read | timed_out
    batch_id: str | None = None


@dataclass(frozen=True)
class BatchInfo:
    received_at: datetime
    resolved_at: datetime | None  # processed time once processed, partially processed or quarantined
    quarantined: bool = False


@dataclass(frozen=True)
class Day:
    date: date
    kind: str
    # When the classification became final: the end of the day, or later if a
    # readings outcome resolved later. For an unresolved day, when it will
    # resolve if that is known (the batch deadline), else None.
    decided_at: datetime | None


def day_start(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=UTC)


def day_end(d: date) -> datetime:
    """A day is complete at 00:00 UTC on the next day."""
    return day_start(d + timedelta(days=1))


def utc_date(t: datetime) -> date:
    return t.astimezone(UTC).date()


def resolution(o: Outcome, batches: dict[str, BatchInfo], deadline: timedelta, now: datetime):
    """For a readings outcome: (resolved, resolved_at, outcome as resolved).

    resolved_at is when it resolved, or when it will if known. The resolved
    outcome is readings for a processed batch, could_not_read for a missing or
    quarantined one.
    """
    due = o.finished_at + deadline
    batch = batches.get(o.batch_id) if o.batch_id else None
    if batch is None or batch.received_at > due:
        # Not arrived by the deadline: missing. A later arrival does not reopen it.
        return now >= due, due, "could_not_read"
    if batch.resolved_at is not None and batch.resolved_at <= now:
        return True, batch.resolved_at, "could_not_read" if batch.quarantined else "readings"
    return False, None, None


def classify(
    d: date,
    *,
    readings: Iterable[datetime],
    outcomes: Iterable[Outcome],
    batches: dict[str, BatchInfo],
    available: Callable[[str, datetime], bool],
    now: datetime,
    deadline: timedelta = timedelta(hours=24),
) -> Day:
    """Classify one day. `readings` are taken_at times of accepted readings; `outcomes` may span any days."""
    end = day_end(d)
    if any(utc_date(t) == d for t in readings):
        return Day(d, READING, end)

    todays = [o for o in outcomes if utc_date(o.finished_at) == d]
    decided_at = end
    resolved = []  # (outcome as resolved, the original outcome)
    pending_until = []  # known resolution times of unresolved readings outcomes; None if unknown
    for o in todays:
        if o.outcome != "readings":
            resolved.append((o.outcome, o))
            continue
        done, at, as_resolved = resolution(o, batches, deadline, now)
        if done:
            decided_at = max(decided_at, at)
            resolved.append((as_resolved, o))
        else:
            pending_until.append(at)
    if pending_until:
        known = None if None in pending_until else max(max(pending_until), end)
        return Day(d, UNRESOLVED, known)
    if any(kind == "no_readings" and available(o.gateway_id, o.finished_at) for kind, o in resolved):
        return Day(d, QUIET, decided_at)
    return Day(d, UNCHECKED, decided_at)


def classify_days(
    first: date,
    *,
    readings: Iterable[datetime],
    outcomes: Iterable[Outcome],
    batches: dict[str, BatchInfo],
    available: Callable[[str, datetime], bool],
    now: datetime,
    deadline: timedelta = timedelta(hours=24),
) -> list[Day]:
    """Every complete day from `first` up to `now`, oldest first."""
    # Group by day once, so each day only looks at its own evidence.
    readings_by_day, outcomes_by_day = defaultdict(list), defaultdict(list)
    for t in readings:
        readings_by_day[utc_date(t)].append(t)
    for o in outcomes:
        outcomes_by_day[utc_date(o.finished_at)].append(o)
    days = []
    d = first
    while day_end(d) <= now:
        days.append(
            classify(
                d,
                readings=readings_by_day.get(d, ()),
                outcomes=outcomes_by_day.get(d, ()),
                batches=batches,
                available=available,
                now=now,
                deadline=deadline,
            )
        )
        d += timedelta(days=1)
    return days
