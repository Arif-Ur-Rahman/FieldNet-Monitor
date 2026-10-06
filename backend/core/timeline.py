"""Appending to and reading the append-only timeline."""

from collections.abc import Iterable
from datetime import datetime

from django.db.models import Max

from core import clock
from core.models import TimelineEntry
from core.timeutil import iso

Kind = TimelineEntry.Kind


def append(
    entity_type: str,
    entity_id: str,
    *,
    kind: str,
    rule: str,
    effective_at: datetime,
    axis: str | None = None,
    from_value: str | None = None,
    to_value: str | None = None,
    evidence_ids: Iterable[str] = (),
    detail: dict | None = None,
    recorded_at: datetime | None = None,
) -> TimelineEntry:
    """Append one entry. The caller must hold a lock on the entity row so seq is race-free."""
    last = TimelineEntry.objects.filter(entity_type=entity_type, entity_id=entity_id).aggregate(m=Max("seq"))["m"]
    return TimelineEntry.objects.create(
        entity_type=entity_type,
        entity_id=entity_id,
        seq=(last or 0) + 1,
        kind=kind,
        axis=axis,
        from_value=from_value,
        to_value=to_value,
        effective_at=effective_at,
        recorded_at=recorded_at or clock.now(),
        rule=rule,
        evidence_ids=[str(e) for e in evidence_ids],
        detail=detail,
    )


def record_transition(
    entity_type: str,
    entity_id: str,
    axis: str,
    from_value: str | None,
    to_value: str | None,
    *,
    rule: str,
    effective_at: datetime,
    evidence_ids: Iterable[str] = (),
    detail: dict | None = None,
) -> TimelineEntry | None:
    """Record a change of one axis. A non-change records nothing and returns None."""
    if from_value == to_value:
        return None
    return append(
        entity_type,
        entity_id,
        kind=Kind.TRANSITION,
        axis=axis,
        from_value=from_value,
        to_value=to_value,
        rule=rule,
        effective_at=effective_at,
        evidence_ids=evidence_ids,
        detail=detail,
    )


def entries(entity_type: str, entity_id: str):
    return TimelineEntry.objects.filter(entity_type=entity_type, entity_id=entity_id).order_by("seq")


def serialize(entry: TimelineEntry) -> dict:
    """The fixed API shape, plus `detail` for corrections and actions."""
    return {
        "seq": entry.seq,
        "kind": entry.kind,
        "axis": entry.axis,
        "from": entry.from_value,
        "to": entry.to_value,
        "effective_at": iso(entry.effective_at),
        "recorded_at": iso(entry.recorded_at),
        "rule": entry.rule,
        "evidence_ids": entry.evidence_ids,
        "detail": entry.detail,
    }
