"""The latest collection rule (the brief's "Latest collection").

With available coverage: take each gateway whose class is available, use its
most recent outcome for the sensor if that cycle finished within the last 24
hours, and pick among those by precedence. A readings outcome whose batch is
missing past its deadline or quarantined counts as could_not_read. An
accepted reading from a batch no cycle mentions counts as a readings outcome
from its gateway, at its taken_at.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from gateways.coverage import AVAILABLE, STOPPED
from sensors.engine.days import BatchInfo, Outcome, resolution

PRECEDENCE = ["readings", "no_readings", "could_not_read", "timed_out"]
WINDOW = timedelta(hours=24)
NOT_CHECKED = "not_checked"
COLLECTION_STOPPED = "collection_stopped"


@dataclass(frozen=True)
class Collection:
    value: str
    # When the value would change by time passing alone (a qualifying outcome
    # turning 24h old, or an unarrived batch reaching its deadline), or None.
    changes_at: datetime | None


def as_shown(o: Outcome, batches: dict[str, BatchInfo], deadline: timedelta, now: datetime):
    """(outcome as collection shows it, when that may still flip).

    A missing or quarantined batch makes readings could_not_read. While the
    batch is unresolved the outcome shows as readings (the gateway reported
    readings and the batch still has time); it flips at the deadline if the
    batch hasn't arrived by then.
    """
    if o.outcome != "readings" or o.batch_id is None:
        # No batch_id on a readings outcome: an accepted reading no cycle mentions. Always readings.
        return o.outcome, None
    resolved, at, value = resolution(o, batches, deadline, now)
    return (value, None) if resolved else ("readings", at)


def latest_collection(
    *,
    now: datetime,
    coverage: str,
    gateway_classes: dict[str, str],
    outcomes: Iterable[Outcome],
    batches: dict[str, BatchInfo],
    unmentioned_readings: Iterable[tuple[str, datetime]] = (),
    deadline: timedelta = timedelta(hours=24),
) -> Collection:
    """`gateway_classes` are the covering gateways' classes at `now`; `unmentioned_readings` are
    (gateway_id, taken_at) of accepted readings from batches no cycle mentions."""
    if coverage == STOPPED:
        return Collection(COLLECTION_STOPPED, None)
    if coverage != AVAILABLE:
        return Collection(NOT_CHECKED, None)

    candidates = list(outcomes) + [Outcome(gw, taken_at, "readings") for gw, taken_at in unmentioned_readings]
    latest = {}  # gateway -> (when, -precedence, shown, flips_at)
    for o in candidates:
        if gateway_classes.get(o.gateway_id) != AVAILABLE or o.finished_at > now:
            continue
        shown, flips_at = as_shown(o, batches, deadline, now)
        key = (o.finished_at, -PRECEDENCE.index(shown), shown, flips_at)
        if o.gateway_id not in latest or key[:2] > latest[o.gateway_id][:2]:
            latest[o.gateway_id] = key

    fresh = [entry for entry in latest.values() if entry[0] >= now - WINDOW]
    if not fresh:
        return Collection(NOT_CHECKED, None)
    value = min((shown for _, _, shown, _ in fresh), key=PRECEDENCE.index)
    changes = [when + WINDOW for when, *_ in fresh] + [flips for *_, flips in fresh if flips is not None]
    return Collection(value, min(changes))
