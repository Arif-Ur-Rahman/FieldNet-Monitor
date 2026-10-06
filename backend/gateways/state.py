"""The gateway status state machine (the brief's "Gateway transitions" table).

Every function runs inside the caller's transaction with the gateway row locked.
Lock order everywhere: gateways before sensors.

Timing. Transitions driven by evidence are effective at the evidence's event
time; the stale timer at last_qualifying_at + stale_after; operator actions at
the server clock. No transition is effective before the current status_since,
so the timeline stays in order. Coverage changes use the server clock (`now`).
"""

from datetime import datetime
from functools import partial

from core import config, timeline
from core.tick import Due
from gateways.models import Cycle, Gateway, Heartbeat, Session

Status = Gateway.Status

# Statuses that automatic rules may move. Suspended, retired and spare only
# change by operator action (or, for spare, by a sensor being assigned).
AUTOMATIC = {Status.NEW, Status.CONNECTED, Status.STALE, Status.DISCONNECTED}


def set_status(
    gateway: Gateway,
    to: str,
    *,
    effective_at: datetime,
    now: datetime,
    rule: str,
    evidence_ids=(),
    detail: dict | None = None,
) -> None:
    """Move the gateway to `to`, record it, and recompute coverage of the sensors it covers."""
    if gateway.status == to:
        return
    effective_at = max(effective_at, gateway.status_since)
    timeline.record_transition(
        "gateway",
        gateway.gateway_id,
        "status",
        gateway.status,
        to,
        rule=rule,
        effective_at=effective_at,
        evidence_ids=evidence_ids,
        detail=detail,
    )
    before = gateway.coverage_class
    gateway.status, gateway.status_since = to, effective_at
    if to != Status.DISCONNECTED:
        gateway.disconnected_since = None
    gateway.save()
    if gateway.coverage_class != before:
        recompute_sensors(gateway, at=now, rule=f"gateway_{to}")


def recompute_sensors(gateway: Gateway, *, at: datetime, rule: str) -> None:
    """Recompute coverage for every sensor this gateway currently covers."""
    from sensors.models import Sensor
    from sensors.services import recompute_coverage

    covered = Sensor.objects.filter(
        pk__in=gateway.assignments.filter(valid_to__isnull=True).values("sensor_id")
    ).select_for_update()
    for sensor in covered.order_by("pk"):
        recompute_coverage(sensor, effective_at=at, rule=rule, evidence_ids=[f"gateway-{gateway.gateway_id}"])


def stale_due(gateway: Gateway) -> datetime | None:
    """When a connected gateway goes stale if no newer qualifying evidence arrives."""
    if gateway.last_qualifying_at is None:
        return None
    return config.deadline(gateway.last_qualifying_at, "stale_after")


def apply_stale(gateway: Gateway, now: datetime) -> None:
    """connected → stale once stale_after has passed since last_qualifying_at, effective at that moment."""
    due = stale_due(gateway)
    if gateway.status == Status.CONNECTED and due is not None and due <= now:
        set_status(gateway, Status.STALE, effective_at=due, now=now, rule="no_qualifying_evidence")


def on_qualifying(gateway: Gateway, event_time: datetime, *, now: datetime, evidence_id: str) -> None:
    """Qualifying evidence at `event_time`, applied at server time `now`."""
    if gateway.status == Status.RETIRED:
        return
    if gateway.last_qualifying_at is None or event_time > gateway.last_qualifying_at:
        # Late evidence moves last_qualifying_at only forward.
        gateway.last_qualifying_at = event_time
        gateway.save(update_fields=["last_qualifying_at"])

    status = gateway.status
    reconnects = (
        status == Status.NEW
        or (status == Status.STALE and event_time >= now - config.config_at(now).stale_after)
        or (status == Status.DISCONNECTED and event_time > gateway.disconnected_since)
    )
    if reconnects:
        set_status(
            gateway,
            Status.CONNECTED,
            effective_at=event_time,
            now=now,
            rule="qualifying_evidence",
            evidence_ids=[evidence_id],
        )
    # Evidence that only just connected the gateway may already be too old to keep it connected.
    apply_stale(gateway, now)


def on_auth_failure(gateway: Gateway, event_time: datetime, *, now: datetime, evidence_id: str) -> None:
    """A heartbeat or cycle with session auth_failed, at `event_time`."""
    if gateway.status == Status.RETIRED:
        return
    if gateway.last_auth_failure_at is None or event_time > gateway.last_auth_failure_at:
        gateway.last_auth_failure_at = event_time
        gateway.save(update_fields=["last_auth_failure_at"])
    newer_than_qualifying = gateway.last_qualifying_at is None or event_time > gateway.last_qualifying_at
    if gateway.status in (Status.NEW, Status.CONNECTED, Status.STALE) and newer_than_qualifying:
        # The first failure of this disconnection; later ones keep it.
        gateway.disconnected_since = event_time
        set_status(
            gateway,
            Status.DISCONNECTED,
            effective_at=event_time,
            now=now,
            rule="auth_failed",
            evidence_ids=[evidence_id],
        )


def derived_status(gateway: Gateway, now: datetime) -> tuple[str, datetime | None]:
    """The status the evidence supports, for unsuspend. Returns (status, disconnected_since)."""
    lq, failure = gateway.last_qualifying_at, gateway.last_auth_failure_at
    if failure is not None and (lq is None or failure > lq):
        return Status.DISCONNECTED, first_auth_failure_after(gateway, lq)
    if lq is None:
        return Status.NEW, None
    if lq >= now - config.config_at(now).stale_after:
        return Status.CONNECTED, None
    return Status.STALE, None


def first_auth_failure_after(gateway: Gateway, after: datetime | None) -> datetime | None:
    """Event time of the first auth failure newer than `after`: where the disconnection began."""
    heartbeats = Heartbeat.objects.filter(gateway=gateway, session=Session.AUTH_FAILED)
    cycles = Cycle.objects.filter(gateway=gateway, session=Session.AUTH_FAILED)
    if after is not None:
        heartbeats, cycles = heartbeats.filter(sent_at__gt=after), cycles.filter(finished_at__gt=after)
    times = [
        t
        for t in (
            heartbeats.order_by("sent_at").values_list("sent_at", flat=True).first(),
            cycles.order_by("finished_at").values_list("finished_at", flat=True).first(),
        )
        if t is not None
    ]
    return min(times) if times else None


def next_stale_due(up_to: datetime):
    """The tick() source: the connected gateway that goes stale first, if that is by `up_to`."""
    gateway = (
        Gateway.objects.filter(status=Status.CONNECTED, last_qualifying_at__isnull=False)
        .order_by("last_qualifying_at", "gateway_id")
        .first()
    )
    due = stale_due(gateway) if gateway is not None else None
    if due is None or due > up_to:
        return None
    return Due(due_at=due, run=partial(run_stale, gateway.gateway_id), label=f"stale {gateway.gateway_id}")


def run_stale(gateway_id: str, effective_at: datetime) -> None:
    gateway = Gateway.objects.select_for_update().get(pk=gateway_id)
    apply_stale(gateway, effective_at)
