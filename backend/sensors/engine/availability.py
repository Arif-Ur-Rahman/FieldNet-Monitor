"""Coverage histories and available time (the brief's "Available time").

A history is a step function over time: ordered segments, the last one
open-ended. The sensor's coverage history comes from its recorded coverage
transitions (server clock); a gateway's class history from its status and
command state transitions.

Dormant waits and sampling windows are measured in available time: time
during which the sensor's coverage is available. They pause while it isn't.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from gateways.coverage import AVAILABLE, gateway_class


@dataclass(frozen=True)
class Segment:
    start: datetime
    end: datetime | None  # None: open-ended (the current value)
    value: str


History = list[Segment]


def history(initial: str, since: datetime, changes: Iterable[tuple[datetime, str]]) -> History:
    """Build a history from `initial` at `since` and (at, value) changes in time order.

    A change at or before `since` replaces the initial value; a change to the
    same value is ignored.
    """
    segments = [Segment(since, None, initial)]
    for at, value in changes:
        last = segments[-1]
        if value == last.value:
            continue
        if at <= last.start:
            segments[-1] = Segment(last.start, None, value)
            continue
        segments[-1] = Segment(last.start, at, last.value)
        segments.append(Segment(at, None, value))
    return segments


def value_at(h: History, t: datetime) -> str | None:
    """The value at `t`, or None before the history starts."""
    for s in reversed(h):
        if s.start <= t:
            return s.value
    return None


def gateway_class_history(
    since: datetime,
    status_changes: Iterable[tuple[datetime, str]],
    command_changes: Iterable[tuple[datetime, str]],
    *,
    status: str = "new",
    command_state: str = "running",
) -> History:
    """A gateway's coverage class over time, from its status and command state changes."""
    initial = gateway_class(status, command_state)
    events = [(at, "status", v) for at, v in status_changes] + [(at, "command", v) for at, v in command_changes]
    # By time only (a stable sort): changes at the same instant keep their recorded order.
    events.sort(key=lambda e: e[0])
    classes = []
    for at, axis, value in events:
        if axis == "status":
            status = value
        else:
            command_state = value
        classes.append((at, gateway_class(status, command_state)))
    return history(initial, since, classes)


def availability(histories: dict[str, History]) -> Callable[[str, datetime], bool]:
    """For day classification: was this gateway's class available at that moment?"""

    def available(gateway_id: str, at: datetime) -> bool:
        h = histories.get(gateway_id)
        return h is not None and value_at(h, at) == AVAILABLE

    return available


def available_between(h: History, a: datetime, b: datetime) -> timedelta:
    """Available time between `a` and `b`."""
    total = timedelta(0)
    for s in h:
        if s.value != AVAILABLE:
            continue
        lo = max(s.start, a)
        hi = b if s.end is None else min(s.end, b)
        if hi > lo:
            total += hi - lo
    return total


def add_available(h: History, start: datetime, amount: timedelta) -> datetime | None:
    """The moment `amount` of available time has passed since `start`.

    None if it can't be reached: the last segment is open-ended, so that only
    happens while coverage is (and stays) unavailable.
    """
    remaining = amount
    for s in h:
        if s.value != AVAILABLE or (s.end is not None and s.end <= start):
            continue
        lo = max(s.start, start)
        if s.end is None or s.end - lo >= remaining:
            return lo + remaining
        remaining -= s.end - lo
    return None


def next_evaluation_at(h: History, start: datetime, amount: timedelta, now: datetime) -> datetime | None:
    """When the wait or window that began at `start` ends if coverage stays available; None while paused."""
    if value_at(h, now) != AVAILABLE:
        return None
    return add_available(h, start, amount)
