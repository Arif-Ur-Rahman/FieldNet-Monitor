"""Gateway registration and the gateway state shape.

Lock order everywhere: gateways (by id) before sensors, to avoid deadlocks.
"""

from django.db import IntegrityError, transaction

from core import clock
from core.errors import Conflict, NotFound
from core.timeutil import iso
from gateways.models import Gateway


def register(gateway_id: str, name: str) -> str:
    """Create a gateway in status new / command state running. Returns its bearer token."""
    now = clock.now()
    token, token_hash = Gateway.new_token()
    try:
        with transaction.atomic():
            Gateway.objects.create(
                gateway_id=gateway_id,
                name=name,
                token_hash=token_hash,
                created_at=now,
                status_since=now,
                command_state_since=now,
            )
    except IntegrityError:
        raise Conflict("duplicate_gateway", f"Gateway {gateway_id} already exists.") from None
    return token


def get(gateway_id: str, *, lock: bool = False) -> Gateway:
    qs = Gateway.objects.select_for_update() if lock else Gateway.objects
    gateway = qs.filter(pk=gateway_id).first()
    if gateway is None:
        raise NotFound("gateway_not_found", f"No gateway {gateway_id}.")
    return gateway


def serialize(g: Gateway) -> dict:
    return {
        "gateway_id": g.gateway_id,
        "name": g.name,
        "status": g.status,
        "status_since": iso(g.status_since),
        "command_state": g.command_state,
        "coverage_class": g.coverage_class,
        "last_heartbeat_at": iso(g.last_heartbeat_at),
        "last_qualifying_at": iso(g.last_qualifying_at),
        "disconnected_since": iso(g.disconnected_since),
        "flags": g.flags,
    }
