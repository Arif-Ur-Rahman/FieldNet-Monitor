"""Receiving batches and reading their state. Processing lives in batches.processing."""

from datetime import datetime

from django.db import IntegrityError, transaction

from batches.models import Batch
from core import timeline
from core.errors import Conflict, NotFound
from gateways.ingest import body_hash
from gateways.models import Gateway

Processing = Batch.Processing


def receive(gateway: Gateway, batch_id: str, data: dict, raw: dict, *, received_at: datetime) -> tuple[Batch, bool]:
    """Store a batch for background processing. Returns (batch, created).

    A repeat with an identical body from the same gateway is (existing, False).
    Any other reuse of the id, from this gateway or another, is a batch_conflict.
    """
    digest = body_hash(raw)
    existing = Batch.objects.select_for_update().filter(batch_id=batch_id).first()
    if existing is None:
        try:
            with transaction.atomic():
                batch = Batch.objects.create(
                    batch_id=batch_id,
                    gateway=gateway,
                    sensor_id=data["sensor_id"],
                    readings=data["readings"],
                    body_hash=digest,
                    received_at=received_at,
                    next_attempt_at=received_at,
                )
        except IntegrityError:
            # A concurrent identical PUT won the race; judge this one against it.
            existing = Batch.objects.select_for_update().get(batch_id=batch_id)
        else:
            timeline.record_transition(
                "batch",
                batch_id,
                "processing",
                None,
                Processing.RECEIVED,
                rule="batch_received",
                effective_at=received_at,
            )
            return batch, True
    if existing.gateway_id != gateway.gateway_id or existing.body_hash != digest:
        raise Conflict("batch_conflict", f"Batch {batch_id} was already received with a different body or gateway.")
    return existing, False


def get(batch_id: str) -> Batch:
    batch = Batch.objects.filter(batch_id=batch_id).first()
    if batch is None:
        raise NotFound("not_found", f"Unknown batch {batch_id}.")
    return batch


def serialize(batch: Batch) -> dict:
    return {
        "processing": batch.processing,
        "attempts": batch.attempts,
        "accepted_count": batch.accepted_count,
        "quarantined": [{"reading_id": q.reading_id, "reason": q.reason} for q in batch.quarantined.all()],
    }
