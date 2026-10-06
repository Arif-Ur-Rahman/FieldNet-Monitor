"""Loading a sensor's evidence from the database into the engine's plain data."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from batches.models import Batch, Reading
from core import config, timeline
from core.config import Config
from gateways.models import CycleResult, Gateway
from sensors.engine.availability import History, gateway_class_history, history
from sensors.engine.days import BatchInfo, Outcome
from sensors.models import Sensor, SensorAction


@dataclass
class Evidence:
    created_at: datetime
    coverage: History
    gateway_classes: dict[str, History]  # every gateway the sensor has outcomes or readings from
    outcomes: list[Outcome]
    batches: dict[str, BatchInfo]
    readings: list[tuple[datetime, str]]  # (taken_at, evidence id), any gateway
    unmentioned_readings: list[tuple[str, datetime]]  # (gateway_id, taken_at) from batches no cycle mentions
    decommission: tuple[datetime, str] | None
    config_at: Callable[[datetime], Config]


def load(sensor: Sensor) -> Evidence:
    outcomes = [
        Outcome(r.gateway_id, r.finished_at, r.outcome, r.batch_id)
        for r in CycleResult.objects.filter(sensor=sensor).order_by("finished_at", "pk")
    ]
    mentioned = {o.batch_id for o in outcomes if o.batch_id}
    batches = {
        b.batch_id: BatchInfo(b.received_at, b.resolved_at, b.processing == Batch.Processing.QUARANTINED)
        for b in Batch.objects.filter(batch_id__in=mentioned)
    }
    readings = list(Reading.objects.filter(sensor=sensor).order_by("taken_at", "pk"))
    gateway_ids = {o.gateway_id for o in outcomes} | {r.gateway_id for r in readings}
    action = SensorAction.objects.filter(sensor=sensor, action="decommission").order_by("at").first()
    return Evidence(
        created_at=sensor.created_at,
        coverage=coverage_history(sensor),
        gateway_classes={g.gateway_id: class_history(g) for g in Gateway.objects.filter(pk__in=gateway_ids)},
        outcomes=outcomes,
        batches=batches,
        readings=[(r.taken_at, f"reading-{r.reading_id}") for r in readings],
        unmentioned_readings=[(r.gateway_id, r.taken_at) for r in readings if r.batch_id not in mentioned],
        decommission=(action.at, action.reason) if action else None,
        config_at=config_lookup(),
    )


def coverage_history(sensor: Sensor) -> History:
    """From the sensor's recorded coverage transitions (server clock)."""
    changes = sorted((e.effective_at, e.to_value) for e in axis_entries("sensor", sensor.sensor_id, "coverage"))
    return history("none", sensor.created_at, changes)


def class_history(gateway: Gateway) -> History:
    """From the gateway's recorded status and command state transitions."""
    return gateway_class_history(
        gateway.created_at,
        [(e.effective_at, e.to_value) for e in axis_entries("gateway", gateway.gateway_id, "status")],
        [(e.effective_at, e.to_value) for e in axis_entries("gateway", gateway.gateway_id, "command_state")],
    )


def axis_entries(entity_type: str, entity_id: str, axis: str):
    return timeline.entries(entity_type, entity_id).filter(kind="transition", axis=axis)


def config_lookup():
    """config_at(t) over the version history, read once."""
    versions = config.history()  # [(effective_from | None, Config)], oldest first

    def config_at(t: datetime) -> Config:
        current = versions[0][1]
        for effective_from, cfg in versions[1:]:
            if effective_from > t:
                break
            current = cfg
        return current

    return config_at
