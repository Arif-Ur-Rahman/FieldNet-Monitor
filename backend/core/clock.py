"""The only place the server reads the time.

Outside TEST_MODE this is wall-clock UTC. In TEST_MODE it is the value last set
through POST /test/clock, so every test is deterministic. Until a test sets it,
TEST_MODE falls back to wall time without storing it.
"""

from datetime import UTC, datetime

from django.conf import settings

from core.errors import Conflict
from core.models import ClockState


def now() -> datetime:
    if settings.TEST_MODE:
        state = ClockState.objects.filter(pk=1).first()
        if state is not None:
            return state.now
    return datetime.now(UTC)


def set_now(new_now: datetime) -> datetime:
    """Move the test clock. It only moves forward; going backwards is a 409."""
    state = ClockState.objects.select_for_update().filter(pk=1).first()
    if state is None:
        ClockState.objects.create(pk=1, now=new_now)
        return new_now
    if new_now < state.now:
        raise Conflict("clock_backwards", f"Clock is at {state.now.isoformat()}; it only moves forward.")
    state.now = new_now
    state.save(update_fields=["now"])
    return new_now
