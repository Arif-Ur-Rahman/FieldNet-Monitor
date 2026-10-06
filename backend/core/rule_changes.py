"""Changing the thresholds (PUT /api/v1/config).

A change adds a ConfigVersion effective at the server clock, writes a
`rule_change` entry on every gateway and sensor whose rules it touches, and
re-evaluates them at once. The replay reads the configuration in force at
each moment, so only behaviour after the change moves: nothing is corrected.
"""

from django.db import transaction

from core import clock, config, timeline
from core.models import ConfigVersion, TimelineEntry

# Which thresholds act on which entities.
GATEWAY_FIELDS = {"stale_after_hours", "command_timeout_minutes"}
SENSOR_FIELDS = set(config.FIELDS) - GATEWAY_FIELDS


def current() -> dict:
    now = clock.now()
    version = ConfigVersion.objects.filter(effective_from__lte=now).order_by("-effective_from").first()
    return {"effective_from": version.effective_from if version else None} | config.config_at(now).fields()


def apply(values: dict) -> dict:
    """Merge `values` into the thresholds in force and record the change. Returns the new current()."""
    from gateways.models import Gateway
    from gateways.state import apply_stale
    from sensors.engine.reconcile import reconcile
    from sensors.models import Sensor

    with transaction.atomic():
        now = clock.now()
        before = config.config_at(now).fields()
        after = before | values
        changed = {k: [before[k], after[k]] for k in config.FIELDS if before[k] != after[k]}
        if not changed:
            return current()
        ConfigVersion.objects.update_or_create(effective_from=now, defaults={"recorded_at": now, **after})

        # Lock order everywhere: gateways before sensors.
        gateways = list(Gateway.objects.select_for_update().order_by("pk"))
        sensors = list(Sensor.objects.select_for_update().order_by("pk"))
        if changed.keys() & GATEWAY_FIELDS:
            detail = {"changed": {k: v for k, v in changed.items() if k in GATEWAY_FIELDS}}
            for gateway in gateways:
                record(gateway.gateway_id, "gateway", now, detail)
                apply_stale(gateway, now)  # a shorter stale threshold may already have passed
        if changed.keys() & SENSOR_FIELDS:
            detail = {"changed": {k: v for k, v in changed.items() if k in SENSOR_FIELDS}}
            for sensor in sensors:
                record(sensor.sensor_id, "sensor", now, detail)
        for sensor in sensors:
            sensor.refresh_from_db()
            reconcile(sensor, now=now, evidence_id="config")
    return current()


def record(entity_id: str, entity_type: str, now, detail: dict) -> None:
    kind = TimelineEntry.Kind.RULE_CHANGE
    timeline.append(entity_type, entity_id, kind=kind, rule="config_changed", effective_at=now, detail=detail)
