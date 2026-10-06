"""Processing batches in the background. tick() runs each due attempt.

An attempt validates every reading, accepts the valid ones and quarantines the
rest with a reason. It runs inside a savepoint: if it fails, nothing it wrote
survives, so a retried batch never double-counts. Attempt k waits 2^(k-1)
minutes before the next; the 5th failure quarantines the batch.
"""

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial

from django.db import transaction

from batches.models import Batch, QuarantinedReading, Reading
from core import timeline
from core.tick import Due
from core.timeutil import is_too_far_ahead, parse_iso
from gateways import commands, state
from gateways.models import Gateway
from sensors.models import Sensor
from testing import faults

log = logging.getLogger(__name__)

Processing = Batch.Processing
MAX_ATTEMPTS = 5
REQUIRED_FIELDS = ("reading_id", "taken_at", "value", "unit")


class InjectedFailure(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    processing: str
    reason: str | None = None
    accepted_count: int = 0
    latest_accepted_taken_at: datetime | None = None


def next_due(up_to: datetime) -> Due | None:
    """The tick() source: the batch whose next attempt is earliest, if it is due by `up_to`."""
    row = (
        Batch.objects.filter(processing__in=Batch.PENDING, next_attempt_at__lte=up_to)
        .order_by("next_attempt_at", "batch_id")
        .values_list("batch_id", "next_attempt_at")
        .first()
    )
    if row is None:
        return None
    batch_id, due_at = row
    return Due(due_at=due_at, run=partial(attempt, batch_id), label=f"batch {batch_id}")


def attempt(batch_id: str, effective_at: datetime) -> None:
    """One processing attempt, at its due time. The caller holds the transaction."""
    # Lock the gateway before the batch, the same order as the PUT, so the two never deadlock.
    gateway_id = Batch.objects.filter(pk=batch_id).values_list("gateway_id", flat=True).get()
    gateway = Gateway.objects.select_for_update().get(pk=gateway_id)
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    if batch.resolved:
        return
    batch.attempts += 1
    before = batch.processing
    # Taken outside the savepoint, so a failed attempt still uses up its injected fault.
    injected = faults.take_processing_failure()
    try:
        with transaction.atomic():
            if injected:
                raise InjectedFailure("injected by /test/faults")
            outcome = process(batch)
    except Exception as exc:
        if not isinstance(exc, InjectedFailure):
            log.exception("Processing batch %s failed (attempt %d)", batch_id, batch.attempts)
        if batch.attempts < MAX_ATTEMPTS:
            batch.processing = Processing.RETRYING
            batch.next_attempt_at = effective_at + timedelta(minutes=2 ** (batch.attempts - 1))
            batch.save()
            record(batch, before, effective_at)
            return
        outcome = quarantine_batch(batch, "processing_failed")
    # The outcome is applied only once the attempt is over, so a failed attempt leaves no trace on the batch.
    batch.processing = outcome.processing
    batch.reason = outcome.reason
    batch.accepted_count = outcome.accepted_count
    batch.latest_accepted_taken_at = outcome.latest_accepted_taken_at
    batch.resolved_at = effective_at
    batch.next_attempt_at = None
    batch.save()
    record(batch, before, effective_at)
    if batch.accepted_count:
        # A processed batch with an accepted reading qualifies, at its latest accepted taken_at.
        evidence_id = f"batch-{batch.batch_id}"
        state.on_qualifying(gateway, batch.latest_accepted_taken_at, now=effective_at, evidence_id=evidence_id)
        commands.check_readings(gateway, batch.accepted.order_by("taken_at", "reading_id"))


def record(batch: Batch, before: str, at: datetime) -> None:
    timeline.record_transition(
        "batch", batch.batch_id, "processing", before, batch.processing, rule="batch_processing", effective_at=at
    )


def process(batch: Batch) -> Outcome:
    """Accept or quarantine every reading. Writes readings; leaves the batch row to the caller."""
    sensor = Sensor.objects.filter(pk=batch.sensor_id).first()
    if sensor is None:
        return quarantine_batch(batch, "unknown_sensor")
    if not batch.readings:
        return quarantine_batch(batch, "empty_batch")

    accepted, rejected = 0, 0
    latest = None
    for position, raw in enumerate(batch.readings):
        reason, reading = check(raw, sensor, batch)
        if reason is None:
            existing = Reading.objects.filter(pk=reading.reading_id).first()
            if existing is None:
                reading.save(force_insert=True)
                accepted += 1
                latest = reading.taken_at if latest is None else max(latest, reading.taken_at)
                continue
            if existing.content_hash == reading.content_hash:
                continue  # the same reading again: ignored, neither counted nor quarantined
            reason = "conflicting_duplicate"
        QuarantinedReading.objects.create(batch=batch, position=position, reading_id=reading_id_of(raw), reason=reason)
        rejected += 1

    if rejected == len(batch.readings):
        return Outcome(Processing.QUARANTINED, reason="all_invalid")
    status = Processing.PARTIALLY_PROCESSED if rejected else Processing.PROCESSED
    return Outcome(status, accepted_count=accepted, latest_accepted_taken_at=latest)


def quarantine_batch(batch: Batch, reason: str) -> Outcome:
    """Quarantine the whole batch, listing every reading under the same reason."""
    QuarantinedReading.objects.bulk_create(
        QuarantinedReading(batch=batch, position=i, reading_id=reading_id_of(raw), reason=reason)
        for i, raw in enumerate(batch.readings)
    )
    return Outcome(Processing.QUARANTINED, reason=reason)


def reading_id_of(raw) -> str | None:
    rid = raw.get("reading_id") if isinstance(raw, dict) else None
    return rid if isinstance(rid, str) and rid else None


def check(raw, sensor: Sensor, batch: Batch) -> tuple[str | None, Reading | None]:
    """Validate one reading. Returns (reason, None) if invalid, else (None, unsaved Reading)."""
    if not isinstance(raw, dict) or any(raw.get(f) is None for f in REQUIRED_FIELDS):
        return "missing_field", None
    reading_id, value, unit = raw["reading_id"], raw["value"], raw["unit"]
    if reading_id_of(raw) is None or len(reading_id) > 128:
        return "invalid_reading_id", None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return "invalid_value", None
    if unit != sensor.unit:
        return "wrong_unit", None
    taken_at = parse_iso(raw["taken_at"])
    if taken_at is None:
        return "invalid_taken_at", None
    if is_too_far_ahead(taken_at, batch.received_at):
        return "timestamp_in_future", None
    reading = Reading(
        reading_id=reading_id,
        batch=batch,
        sensor=sensor,
        gateway_id=batch.gateway_id,
        taken_at=taken_at,
        value=float(value),
        unit=unit,
        content_hash=content_hash(sensor.sensor_id, taken_at, float(value), unit),
    )
    return None, reading


def content_hash(sensor_id: str, taken_at: datetime, value: float, unit: str) -> str:
    content = [sensor_id, taken_at.isoformat(), value, unit]
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()
