"""Sensor registration, coverage assignment, decommission and the sensor state shape."""

from datetime import datetime

from django.db import IntegrityError, transaction

from core import clock, timeline
from core.errors import Conflict, NotFound
from core.models import TimelineEntry
from core.timeutil import iso
from gateways.coverage import sensor_coverage
from gateways.models import Gateway
from sensors.models import CoverageAssignment, Sensor, SensorAction

Kind = TimelineEntry.Kind


def register(sensor_id: str, sensor_type: str) -> Sensor:
    now = clock.now()
    try:
        with transaction.atomic():
            return Sensor.objects.create(sensor_id=sensor_id, type=sensor_type, created_at=now, lifecycle_since=now)
    except IntegrityError:
        raise Conflict("duplicate_sensor", f"Sensor {sensor_id} already exists.") from None


def get(sensor_id: str, *, lock: bool = False) -> Sensor:
    qs = Sensor.objects.select_for_update() if lock else Sensor.objects
    sensor = qs.filter(pk=sensor_id).first()
    if sensor is None:
        raise NotFound("sensor_not_found", f"No sensor {sensor_id}.")
    return sensor


def covering_gateways(sensor: Sensor) -> list[Gateway]:
    return list(Gateway.objects.filter(assignments__sensor=sensor, assignments__valid_to__isnull=True))


def recompute_coverage(sensor: Sensor, *, effective_at: datetime, rule: str, evidence_ids=()) -> bool:
    """Derive the sensor's coverage from its current gateways; record a change. Returns True if it changed."""
    new = sensor_coverage(g.coverage_class for g in covering_gateways(sensor))
    if new == sensor.coverage:
        return False
    timeline.record_transition(
        "sensor",
        sensor.sensor_id,
        "coverage",
        sensor.coverage,
        new,
        rule=rule,
        effective_at=effective_at,
        evidence_ids=evidence_ids,
    )
    sensor.coverage = new
    sensor.save(update_fields=["coverage"])
    return True


def set_coverage(sensor_id: str, gateway_ids: list[str]) -> Sensor:
    """Replace the set of gateways covering a sensor (timed by the server clock)."""
    wanted = sorted(set(gateway_ids))
    with transaction.atomic():
        gateways = {g.pk: g for g in Gateway.objects.select_for_update().filter(pk__in=wanted).order_by("pk")}
        missing = [gid for gid in wanted if gid not in gateways]
        if missing:
            raise NotFound("gateway_not_found", f"No gateway {', '.join(missing)}.")
        retired = [gid for gid, g in gateways.items() if g.status == Gateway.Status.RETIRED]
        if retired:
            raise Conflict("gateway_retired", f"Gateway {', '.join(retired)} is retired.")
        sensor = get(sensor_id, lock=True)
        now = clock.now()

        current = {a.gateway_id: a for a in sensor.assignments.filter(valid_to__isnull=True)}
        for gid, assignment in current.items():
            if gid not in gateways:
                assignment.valid_to = now
                assignment.save(update_fields=["valid_to"])
        for gid, gateway in gateways.items():
            if gid in current:
                continue
            CoverageAssignment.objects.create(sensor=sensor, gateway=gateway, valid_from=now)
            if gateway.status == Gateway.Status.SPARE:
                timeline.record_transition(
                    "gateway",
                    gid,
                    "status",
                    gateway.status,
                    Gateway.Status.NEW,
                    rule="sensor_assigned",
                    effective_at=now,
                    evidence_ids=[sensor_id],
                )
                gateway.status, gateway.status_since = Gateway.Status.NEW, now
                gateway.save(update_fields=["status", "status_since"])

        recompute_coverage(sensor, effective_at=now, rule="assignment_changed")
        return sensor


def decommission(sensor_id: str, reason: str) -> Sensor:
    """Operator decommission: terminal; any later action is 409."""
    with transaction.atomic():
        sensor = get(sensor_id, lock=True)
        if sensor.lifecycle == Sensor.Lifecycle.DECOMMISSIONED:
            raise Conflict("sensor_decommissioned", f"Sensor {sensor_id} is decommissioned.")
        now = clock.now()
        action = SensorAction.objects.create(sensor=sensor, action="decommission", reason=reason, at=now)
        timeline.append(
            "sensor",
            sensor_id,
            kind=Kind.ACTION,
            rule="decommission",
            effective_at=now,
            evidence_ids=[f"action-{action.pk}"],
            detail={"reason": reason},
        )
        timeline.record_transition(
            "sensor",
            sensor_id,
            "lifecycle",
            sensor.lifecycle,
            Sensor.Lifecycle.DECOMMISSIONED,
            rule="decommission",
            effective_at=now,
            evidence_ids=[f"action-{action.pk}"],
            detail={"reason": reason},
        )
        sensor.lifecycle = Sensor.Lifecycle.DECOMMISSIONED
        sensor.lifecycle_reason = reason
        sensor.lifecycle_since = now
        sensor.next_evaluation_at = None
        sensor.save()
        return sensor


def serialize(s: Sensor) -> dict:
    return {
        "sensor_id": s.sensor_id,
        "type": s.type,
        "lifecycle": s.lifecycle,
        "lifecycle_reason": s.lifecycle_reason,
        "lifecycle_since": iso(s.lifecycle_since),
        "collection": s.collection,
        "coverage": s.coverage,
        "quiet_checked_days": s.quiet_checked_days,
        "sampling_cycles_done": s.sampling_cycles_done,
        "next_evaluation_at": iso(s.next_evaluation_at),
    }
