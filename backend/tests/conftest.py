from datetime import UTC, datetime

import pytest


@pytest.fixture
def test_mode(settings):
    settings.TEST_MODE = True
    return settings


def at(day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Day n of the worked example: 00:00 UTC on the n-th day after day 0 (2026-01-01)."""
    from datetime import timedelta

    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day, hours=hour, minutes=minute)
