"""ISO 8601 UTC formatting and parsing shared by every API."""

from datetime import UTC, datetime, timedelta

from django.utils.dateparse import parse_datetime


def iso(value: datetime | None) -> str | None:
    """Render as ISO 8601 UTC with a Z suffix, e.g. 2026-01-01T12:00:00Z."""
    if value is None:
        return None
    text = value.astimezone(UTC).isoformat()
    return text.replace("+00:00", "Z")


def parse_iso(value: str) -> datetime | None:
    """Parse ISO 8601. A naive value is taken as UTC. Returns None if unparseable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


MAX_DEVICE_SKEW = timedelta(minutes=5)


def is_too_far_ahead(event_time: datetime, received_at: datetime) -> bool:
    """A device timestamp more than 5 minutes after its received time is invalid."""
    return event_time > received_at + MAX_DEVICE_SKEW
