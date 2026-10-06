"""Stop and resume: commands, acknowledgements, timeouts and stop periods.

Commands are ordered per gateway by seq; the latest one issued is the desired
state. Every function runs inside the caller's transaction with the gateway
row locked (gateways before sensors).
"""

from datetime import datetime

from core import config, timeline
from core.errors import Conflict
from gateways import state
from gateways.models import Command, Gateway

CommandState = Gateway.CommandState

ILLEGAL = {
    Command.Type.STOP: {CommandState.STOP_PENDING, CommandState.STOPPED},
    Command.Type.RESUME: {CommandState.RUNNING, CommandState.RESUME_PENDING},
}
PENDING = {Command.Type.STOP: CommandState.STOP_PENDING, Command.Type.RESUME: CommandState.RESUME_PENDING}


def set_command_state(
    gateway: Gateway,
    to: str,
    *,
    effective_at: datetime,
    now: datetime,
    rule: str,
    evidence_ids=(),
) -> None:
    """Move the command state, record it, and recompute coverage if the gateway's class changes."""
    if gateway.command_state == to:
        return
    effective_at = max(effective_at, gateway.command_state_since)
    timeline.record_transition(
        "gateway",
        gateway.gateway_id,
        "command_state",
        gateway.command_state,
        to,
        rule=rule,
        effective_at=effective_at,
        evidence_ids=evidence_ids,
    )
    before = gateway.coverage_class
    gateway.command_state, gateway.command_state_since = to, effective_at
    gateway.save()
    if gateway.coverage_class != before:
        state.recompute_sensors(gateway, at=now, rule=f"command_{to}")


def check_allowed(gateway: Gateway, command_type: str) -> None:
    if gateway.command_state in ILLEGAL[command_type]:
        raise Conflict(
            "illegal_command", f"Cannot {command_type} gateway {gateway.gateway_id} while {gateway.command_state}."
        )


def issue(gateway: Gateway, command_type: str, *, now: datetime) -> Command:
    """Issue a stop or resume. It supersedes the previous command."""
    check_allowed(gateway, command_type)
    latest = gateway.commands.order_by("-seq").first()
    if latest is not None:
        latest.superseded = True
        latest.save(update_fields=["superseded"])
    command = Command.objects.create(
        gateway=gateway,
        seq=(latest.seq if latest else 0) + 1,
        type=command_type,
        issued_at=now,
        timeout_at=now + config.config_at(now).command_timeout,
    )
    set_command_state(
        gateway,
        PENDING[command_type],
        effective_at=now,
        now=now,
        rule=command_type,
        evidence_ids=[f"command-{command.command_id}"],
    )
    return command
