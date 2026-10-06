"""ISO 8601 UTC formatting and parsing shared by every API."""

from datetime import UTC, datetime

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
