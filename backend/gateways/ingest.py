"""Recording gateway evidence: heartbeats and cycles.

Each function runs inside the caller's transaction with the gateway row locked.
New evidence first updates the gateway (gateways.state), which recomputes
coverage; applying the evidence to sensors comes after, in the sensor engine.
A repeated request changes nothing.
"""

import hashlib
import json
from datetime import datetime

from django.db.models import Q

from core.errors import Conflict, Unprocessable
from core.timeutil import is_too_far_ahead
from gateways import state
from gateways.models import Cycle, CycleResult, Gateway, Heartbeat, Session
from sensors.engine.reconcile import reconcile_sensors
from sensors.models import Sensor

Outcome = CycleResult.Outcome
REPORTED_TO_RECORDED = {
    "readings": Outcome.READINGS,
    "no_readings": Outcome.NO_READINGS,
    "could_not_read": Outcome.COULD_NOT_READ,
    "timeout": Outcome.TIMED_OUT,
}


# An ok cycle qualifies with at least one of these among its recorded (covered) results.
QUALIFYING_OUTCOMES = {"readings", "no_readings"}


def body_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reject_future(received_at: datetime, **event_times: datetime) -> None:
    for name, value in event_times.items():
        if is_too_far_ahead(value, received_at):
            raise Unprocessable("timestamp_in_future", f"{name} is more than 5 minutes after the received time.")


def record_heartbeat(gateway: Gateway, *, sent_at: datetime, session: str, received_at: datetime) -> Heartbeat:
    reject_future(received_at, sent_at=sent_at)
    heartbeat, created = Heartbeat.objects.get_or_create(
        gateway=gateway, sent_at=sent_at, session=session, defaults={"received_at": received_at}
    )
    # last_heartbeat_at is the received time of the latest heartbeat, whatever the session.
    if gateway.last_heartbeat_at is None or received_at > gateway.last_heartbeat_at:
        gateway.last_heartbeat_at = received_at
        gateway.save(update_fields=["last_heartbeat_at"])
    # A heartbeat never qualifies; with auth_failed it disconnects.
    if created and session == Session.AUTH_FAILED:
        state.on_auth_failure(gateway, sent_at, now=received_at, evidence_id=f"heartbeat-{heartbeat.pk}")
    return heartbeat


def covered_sensor_ids(gateway: Gateway, sensor_ids) -> set[str]:
    return set(
        Sensor.objects.filter(
            Q(assignments__gateway=gateway) & Q(assignments__valid_to__isnull=True), sensor_id__in=list(sensor_ids)
        ).values_list("sensor_id", flat=True)
    )


def record_cycle(gateway: Gateway, data: dict, raw: dict, *, received_at: datetime) -> tuple[Cycle, bool]:
    """Store a cycle. Returns (cycle, created). A repeat with an identical body is (existing, False)."""
    digest = body_hash(raw)
    existing = Cycle.objects.filter(gateway=gateway, cycle_id=data["cycle_id"]).first()
    if existing is not None:
        if existing.body_hash != digest:
            raise Conflict("cycle_conflict", f"Cycle {data['cycle_id']} was already received with a different body.")
        return existing, False

    reject_future(received_at, started_at=data["started_at"], finished_at=data["finished_at"])
    results = data["results"]
    covered = covered_sensor_ids(gateway, (r["sensor_id"] for r in results))
    ignored = [r["sensor_id"] for r in results if r["sensor_id"] not in covered]

    cycle = Cycle.objects.create(
        gateway=gateway,
        cycle_id=data["cycle_id"],
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        session=data["session"],
        received_at=received_at,
        body_hash=digest,
        ignored=ignored,
    )
    auth_failed = data["session"] == Session.AUTH_FAILED
    CycleResult.objects.bulk_create(
        CycleResult(
            cycle=cycle,
            sensor_id=r["sensor_id"],
            gateway=gateway,
            finished_at=cycle.finished_at,
            # With session auth_failed every outcome is recorded as could_not_read.
            outcome=Outcome.COULD_NOT_READ if auth_failed else REPORTED_TO_RECORDED[r["outcome"]],
            reported_outcome=r["outcome"],
            batch_id=None if auth_failed else r.get("batch_id"),
        )
        for r in results
        if r["sensor_id"] in covered
    )
    evidence_id = f"cycle-{cycle.pk}"
    if auth_failed:
        state.on_auth_failure(gateway, cycle.finished_at, now=received_at, evidence_id=evidence_id)
    elif any(r["outcome"] in QUALIFYING_OUTCOMES for r in results if r["sensor_id"] in covered):
        state.on_qualifying(gateway, cycle.finished_at, now=received_at, evidence_id=evidence_id)
    # Gateway first (above), which recomputed coverage; then the evidence goes to the sensors.
    reconcile_sensors(covered, now=received_at, evidence_id=evidence_id)
    return cycle, True
