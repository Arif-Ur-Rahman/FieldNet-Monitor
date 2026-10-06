"""Operator actions on a gateway: suspend, unsuspend, mark_spare, retire, stop and resume.

Each action writes an `action` timeline entry, then the status or command state
transition it causes, both at the server clock.
"""

from django.db import transaction

from core import clock, timeline
from core.errors import Conflict
from core.models import TimelineEntry
from gateways import commands, services, state
from gateways.models import Gateway

Status = Gateway.Status
Kind = TimelineEntry.Kind
ACTIONS = ["suspend", "unsuspend", "mark_spare", "retire", "stop", "resume"]


def perform(gateway_id: str, action: str, reason: str | None) -> Gateway:
    with transaction.atomic():
        gateway = services.get(gateway_id, lock=True)
        check_allowed(gateway, action)
        now = clock.now()
        detail = {"reason": reason} if reason else None
        timeline.append("gateway", gateway_id, kind=Kind.ACTION, rule=action, effective_at=now, detail=detail)
        if action == "suspend":
            gateway.suspended_reason = reason
            state.set_status(gateway, Status.SUSPENDED, effective_at=now, now=now, rule="suspend", detail=detail)
        elif action == "unsuspend":
            to, disconnected_since = state.derived_status(gateway, now)
            gateway.suspended_reason = None
            gateway.disconnected_since = disconnected_since
            state.set_status(gateway, to, effective_at=now, now=now, rule="unsuspend", detail=detail)
        elif action == "mark_spare":
            state.set_status(gateway, Status.SPARE, effective_at=now, now=now, rule="mark_spare", detail=detail)
        elif action == "retire":
            state.set_status(gateway, Status.RETIRED, effective_at=now, now=now, rule="retire", detail=detail)
        elif action in ("stop", "resume"):
            commands.issue(gateway, action, now=now)
        return gateway


def check_allowed(gateway: Gateway, action: str) -> None:
    """409 for an action the gateway's current status does not allow."""
    gid, status = gateway.gateway_id, gateway.status
    if status == Status.RETIRED:
        raise Conflict("gateway_retired", f"Gateway {gid} is retired.")
    if action == "suspend" and status == Status.SUSPENDED:
        raise Conflict("already_suspended", f"Gateway {gid} is already suspended.")
    if action == "unsuspend" and status != Status.SUSPENDED:
        raise Conflict("not_suspended", f"Gateway {gid} is not suspended.")
    if action == "mark_spare":
        if status != Status.NEW:
            raise Conflict("illegal_transition", f"Only a new gateway can be marked spare; {gid} is {status}.")
        if gateway.assignments.filter(valid_to__isnull=True).exists():
            raise Conflict("gateway_covers_sensors", f"Gateway {gid} covers sensors; it cannot be spare.")
    if action in ("stop", "resume"):
        commands.check_allowed(gateway, action)
