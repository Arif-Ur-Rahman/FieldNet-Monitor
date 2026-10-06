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


@pytest.fixture
def api():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def clock_at(test_mode, db):
    """Set the test clock: clock_at(day, hour=0, minute=0)."""
    from core import clock

    def set_(day: int, hour: int = 0, minute: int = 0):
        return clock.set_now(at(day, hour, minute))

    return set_
