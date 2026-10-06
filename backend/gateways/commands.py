"""Stop and resume: commands, acknowledgements, timeouts and stop periods.

Commands are ordered per gateway by seq; the latest one issued is the desired
state. Every function runs inside the caller's transaction with the gateway
row locked (gateways before sensors).
"""

from datetime import datetime
from functools import partial

from batches.models import Reading
from core import config, timeline
from core.errors import Conflict, NotFound, Unprocessable
from core.models import TimelineEntry
from core.tick import Due
from core.timeutil import is_too_far_ahead
from gateways import state
from gateways.models import Command, Gateway, StopPeriod

CommandState = Gateway.CommandState
Kind = TimelineEntry.Kind

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


def latest_unacknowledged(gateway: Gateway) -> list[Command]:
    """What GET /gw/v1/commands returns: the latest command, only while it is unacknowledged."""
    latest = gateway.commands.order_by("-seq").first()
    return [latest] if latest is not None and latest.acked_at is None else []


def acknowledge(gateway: Gateway, command_id: str, acked_at: datetime, *, received_at: datetime) -> None:
    """Record an acknowledgement. The first one wins; a repeat changes nothing.

    Every first ack writes an `ack` entry. Only an ack of the latest command
    changes the command state; an ack of a superseded command is recorded only.
    """
    command = Command.objects.filter(pk=command_id, gateway=gateway).first()
    if command is None:
        raise NotFound("command_not_found", f"No command {command_id} for gateway {gateway.gateway_id}.")
    if is_too_far_ahead(acked_at, received_at):
        raise Unprocessable("timestamp_in_future", "acked_at is more than 5 minutes after the received time.")
    if command.acked_at is not None:
        return
    command.acked_at, command.ack_received_at = acked_at, received_at
    command.save(update_fields=["acked_at", "ack_received_at"])
    evidence_ids = [f"command-{command.command_id}"]
    timeline.append(
        "gateway",
        gateway.gateway_id,
        kind=Kind.ACK,
        rule=f"ack_{command.type}",
        effective_at=acked_at,
        evidence_ids=evidence_ids,
        detail={"command_id": command.command_id, "seq": command.seq, "superseded": command.superseded},
    )
    if command.type == Command.Type.STOP:
        open_stop_period(gateway, command)
    else:
        close_stop_periods(gateway, command)
    if not command.superseded:
        to = CommandState.STOPPED if command.type == Command.Type.STOP else CommandState.RUNNING
        set_command_state(
            gateway, to, effective_at=acked_at, now=received_at, rule=f"ack_{command.type}", evidence_ids=evidence_ids
        )


def superseding_resume(stop: Command) -> Command | None:
    """The resume that superseded a stop: the first resume issued after it."""
    return stop.gateway.commands.filter(type=Command.Type.RESUME, seq__gt=stop.seq).order_by("seq").first()


def open_stop_period(gateway: Gateway, stop: Command) -> StopPeriod:
    """A stop period starts at the stop's acked_at. If its resume was already acked, it is closed at once."""
    resume = superseding_resume(stop)
    ended_at = None
    if resume is not None and resume.acked_at is not None:
        ended_at = max(resume.acked_at, stop.acked_at)
    period = StopPeriod.objects.create(gateway=gateway, stop=stop, started_at=stop.acked_at, ended_at=ended_at)
    # A late ack: readings already accepted inside the period count too.
    taken = Reading.objects.filter(gateway=gateway, taken_at__gte=period.started_at)
    if ended_at is not None:
        taken = taken.filter(taken_at__lte=ended_at)
    check_readings(gateway, taken.order_by("taken_at", "reading_id"), periods=[period])
    return period


def close_stop_periods(gateway: Gateway, resume: Command) -> None:
    """A resume's ack ends every open stop period of the stops it superseded."""
    for period in gateway.stop_periods.filter(ended_at__isnull=True, stop__seq__lt=resume.seq):
        period.ended_at = max(resume.acked_at, period.started_at)
        period.save(update_fields=["ended_at"])
    clear_flag(gateway, resume)


FAILED = {Command.Type.STOP: CommandState.STOP_FAILED, Command.Type.RESUME: CommandState.RESUME_FAILED}


def next_timeout_due(up_to: datetime) -> Due | None:
    """The tick() source: the latest unacknowledged command whose timeout passes first, if by `up_to`."""
    command = (
        Command.objects.filter(acked_at__isnull=True, superseded=False, timed_out=False, timeout_at__lte=up_to)
        .order_by("timeout_at", "command_id")
        .first()
    )
    if command is None:
        return None
    return Due(due_at=command.timeout_at, run=partial(run_timeout, command.command_id), label=f"timeout {command.pk}")


def run_timeout(command_id: str, effective_at: datetime) -> None:
    """stop_pending → stop_failed, resume_pending → resume_failed, effective at the timeout."""
    gateway_id = Command.objects.filter(pk=command_id).values_list("gateway_id", flat=True).get()
    gateway = Gateway.objects.select_for_update().get(pk=gateway_id)
    command = Command.objects.select_for_update().get(pk=command_id)
    # Re-checked under the lock: an ack, a newer command or another worker may have got here first.
    if command.acked_at is not None or command.superseded or command.timed_out:
        return
    command.timed_out = True
    command.save(update_fields=["timed_out"])
    if gateway.command_state == PENDING[command.type]:
        set_command_state(
            gateway,
            FAILED[command.type],
            effective_at=command.timeout_at,
            now=effective_at,
            rule="command_timeout",
            evidence_ids=[f"command-{command_id}"],
        )


FLAG = "collecting_after_stop"


def check_readings(gateway: Gateway, readings, *, periods=None) -> None:
    """Flag accepted readings from this gateway taken inside one of its stop periods.

    Each such reading is kept and counted, and writes a `flag` entry. The
    gateway's flag is raised only by a reading in the current (open) period.
    A period includes its stop's acked_at and its resume's acked_at.
    """
    periods = list(gateway.stop_periods.all()) if periods is None else periods
    for reading in readings:
        period = next((p for p in periods if inside(p, reading.taken_at)), None)
        if period is None:
            continue
        before = gateway.flags
        if not period.has_readings:
            period.has_readings = True
            period.save(update_fields=["has_readings"])
        if period.ended_at is None and not gateway.collecting_after_stop:
            gateway.collecting_after_stop = True
            gateway.save(update_fields=["collecting_after_stop"])
        timeline.append(
            "gateway",
            gateway.gateway_id,
            kind=Kind.FLAG,
            axis="flags",
            from_value=",".join(before) or None,
            to_value=",".join(gateway.flags) or None,
            rule=FLAG,
            effective_at=reading.taken_at,
            evidence_ids=[f"reading-{reading.reading_id}"],
            detail={"stop_command_id": period.stop_id, "period_open": period.ended_at is None},
        )


def inside(period: StopPeriod, taken_at: datetime) -> bool:
    return period.started_at <= taken_at and (period.ended_at is None or taken_at <= period.ended_at)


def clear_flag(gateway: Gateway, resume: Command) -> None:
    """The flag clears when a resume is acknowledged and no open stop period remains with readings."""
    if not gateway.collecting_after_stop:
        return
    if gateway.stop_periods.filter(ended_at__isnull=True, has_readings=True).exists():
        return
    gateway.collecting_after_stop = False
    gateway.save(update_fields=["collecting_after_stop"])
    timeline.append(
        "gateway",
        gateway.gateway_id,
        kind=Kind.FLAG,
        axis="flags",
        from_value=FLAG,
        to_value=None,
        rule="resume_acked",
        effective_at=resume.acked_at,
        evidence_ids=[f"command-{resume.command_id}"],
    )
