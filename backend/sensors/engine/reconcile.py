"""Reconcile: replay a sensor and record what changed. The only engine part that writes.

The recorded lifecycle history is read back from the timeline: transitions in
order, where a correction's recomputed transitions replace everything before
it. Then:
  the replay matches          record nothing
  the replay extends it       append the new steps as transitions
  a past step differs         append one correction entry (earlier entries stay)
The sensor's cached fields are then set from the replay. Callers hold a lock
on the sensor row.
"""

from datetime import datetime
from functools import partial

from core import timeline
from core.models import TimelineEntry
from core.tick import Due
from core.timeutil import iso, parse_iso
from sensors.engine.availability import availability, value_at
from sensors.engine.collection import latest_collection
from sensors.engine.days import UNRESOLVED, classify_days, day_end, resolution, utc_date
from sensors.engine.evidence import load
from sensors.engine.replay import ACTIVE, replay
from sensors.models import Sensor

Kind = TimelineEntry.Kind


def reconcile(sensor: Sensor, *, now: datetime, evidence_id: str | None = None) -> None:
    ev = load(sensor)
    deadline = ev.config_at(now).batch_deadline
    available = availability(ev.gateway_classes)
    days = classify_days(
        utc_date(ev.created_at),
        readings=[t for t, _ in ev.readings],
        outcomes=ev.outcomes,
        batches=ev.batches,
        available=available,
        now=now,
        deadline=deadline,
    )
    pending = [o for o in ev.outcomes if o.outcome == "readings" and not resolution(o, ev.batches, deadline, now)[0]]
    result = replay(
        created_at=ev.created_at,
        now=now,
        coverage=ev.coverage,
        days=days,
        readings=ev.readings,
        no_readings=[
            o.finished_at for o in ev.outcomes if o.outcome == "no_readings" and available(o.gateway_id, o.finished_at)
        ],
        pending_readings=[o.finished_at for o in pending],
        decommission=ev.decommission,
        config_at=ev.config_at,
    )
    record(sensor, result, evidence_id)

    coverage = value_at(ev.coverage, now) or "none"
    collection = latest_collection(
        now=now,
        coverage=coverage,
        gateway_classes={gw: value_at(h, now) for gw, h in ev.gateway_classes.items()},
        outcomes=ev.outcomes,
        batches=ev.batches,
        unmentioned_readings=ev.unmentioned_readings,
        deadline=deadline,
    )
    if collection.value != sensor.collection:
        timeline.record_transition(
            "sensor",
            sensor.sensor_id,
            "collection",
            sensor.collection,
            collection.value,
            rule="latest_collection",
            effective_at=now,
            evidence_ids=[evidence_id] if evidence_id else [],
        )

    # The next moment the result could change by time alone.
    due = [result.next_evaluation_at, collection.changes_at]
    due += [d.decided_at for d in days if d.kind == UNRESOLVED]
    due += [o.finished_at + deadline for o in pending]
    if result.lifecycle == ACTIVE:
        due.append(day_end(utc_date(now)))

    sensor.lifecycle = result.lifecycle
    sensor.lifecycle_reason = result.reason
    sensor.lifecycle_since = result.since
    sensor.quiet_checked_days = result.quiet_checked_days
    sensor.sampling_cycles_done = result.sampling_cycles_done
    sensor.next_evaluation_at = result.next_evaluation_at
    sensor.collection = collection.value
    sensor.reconcile_at = min((t for t in due if t is not None and t > now), default=None)
    sensor.save()


def step(t) -> tuple:
    return (t.at, t.to_state, t.to_reason)


def recorded_history(sensor_id: str) -> list[tuple]:
    """The lifecycle history as recorded: (at, state, reason) steps."""
    steps = []
    for e in timeline.entries("sensor", sensor_id).filter(axis="lifecycle"):
        if e.kind == Kind.TRANSITION:
            steps.append((e.effective_at, e.to_value, (e.detail or {}).get("reason")))
        elif e.kind == Kind.CORRECTION:
            steps = [(parse_iso(t["at"]), t["to"], t["reason"]) for t in e.detail["transitions"]]
    return steps


def record(sensor: Sensor, result, evidence_id: str | None) -> None:
    recorded = recorded_history(sensor.sensor_id)
    replayed = [step(t) for t in result.transitions]
    if replayed[: len(recorded)] == recorded:
        for t in result.transitions[len(recorded) :]:
            evidence = list(t.evidence_ids) or ([evidence_id] if evidence_id else [])
            timeline.append(
                "sensor",
                sensor.sensor_id,
                kind=Kind.TRANSITION,
                axis="lifecycle",
                from_value=t.from_state,
                to_value=t.to_state,
                rule=t.rule,
                effective_at=t.at,
                evidence_ids=evidence,
                detail={"reason": t.to_reason} if t.to_reason else None,
            )
        return

    # A past step differs: one correction entry, effective where the histories diverge.
    first = next(i for i, (a, b) in enumerate(zip(recorded + [None], replayed + [None], strict=False)) if a != b)
    diverged_at = min(s[0] for s in (recorded[first : first + 1] + replayed[first : first + 1]))
    previous = recorded[-1] if recorded else (None, "pending", None)
    timeline.append(
        "sensor",
        sensor.sensor_id,
        kind=Kind.CORRECTION,
        axis="lifecycle",
        from_value=previous[1],
        to_value=result.lifecycle,
        rule="recomputed",
        effective_at=diverged_at,
        evidence_ids=[evidence_id] if evidence_id else [],
        detail={
            "previous": {"lifecycle": previous[1], "reason": previous[2]},
            "corrected": {"lifecycle": result.lifecycle, "reason": result.reason},
            "transitions": [
                {"at": iso(t.at), "from": t.from_state, "to": t.to_state, "reason": t.to_reason, "rule": t.rule}
                for t in result.transitions
            ],
        },
    )


def reconcile_sensors(sensor_ids, *, now: datetime, evidence_id: str | None = None) -> None:
    """Lock and reconcile these sensors (in id order, after the caller's gateway lock)."""
    for sensor in Sensor.objects.select_for_update().filter(pk__in=list(sensor_ids)).order_by("pk"):
        reconcile(sensor, now=now, evidence_id=evidence_id)


def next_due(up_to: datetime) -> Due | None:
    """The tick() source: the sensor whose result may change first by time alone, if by `up_to`."""
    row = (
        Sensor.objects.filter(reconcile_at__lte=up_to)
        .order_by("reconcile_at", "pk")
        .values_list("pk", "reconcile_at")
        .first()
    )
    if row is None:
        return None
    return Due(due_at=row[1], run=partial(run_due, row[0]), label=f"sensor {row[0]}")


def run_due(sensor_id: str, effective_at: datetime) -> None:
    reconcile_sensors([sensor_id], now=effective_at)
