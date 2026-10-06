"""The sensor lifecycle as a pure replay (the brief's "Sensor transitions").

replay() walks forward from the sensor's creation to `now`, applying events in
time order. At the same instant: decommission, coverage, readings, timers.

  decommission  terminal
  coverage      none: anything but pending/decommissioned → retired(no_live_coverage);
                back from none: retired(no_live_coverage) → pending, counters reset
  reading       pending → active; dormant, sampling, retired(no_readings) → active
                (also under stopped or recoverable coverage, never under none)
  day complete  active: a quiet day after the last reading day counts; the Nth
                → dormant at 00:00 after it. An undecided day blocks later days.
  dormant wait  N days of available time → sampling
  window end    no_readings seen, no reading → dormant (or retired(no_readings)
                after the Nth cycle); nothing seen → a new window

The result is the list of transitions and the state at `now`. The stored
sensor state is a cache of it; reconcile (#15) records the differences.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from core.config import Config
from sensors.engine.availability import History, add_available, next_evaluation_at, value_at
from sensors.engine.days import QUIET, UNRESOLVED, Day, day_end, utc_date

PENDING, ACTIVE, DORMANT, SAMPLING, RETIRED, DECOMMISSIONED = (
    "pending",
    "active",
    "dormant",
    "sampling",
    "retired",
    "decommissioned",
)
NO_READINGS, NO_LIVE_COVERAGE = "no_readings", "no_live_coverage"

# Same-instant order.
DECOMMISSION, COVERAGE, READING, TIMER = range(4)


@dataclass(frozen=True)
class Transition:
    at: datetime
    from_state: str
    from_reason: str | None
    to_state: str
    to_reason: str | None
    rule: str
    evidence_ids: tuple[str, ...] = ()


@dataclass
class Result:
    lifecycle: str
    reason: str | None
    since: datetime
    quiet_checked_days: int = 0
    sampling_cycles_done: int = 0
    next_evaluation_at: datetime | None = None
    transitions: list[Transition] = field(default_factory=list)


def replay(
    *,
    created_at: datetime,
    now: datetime,
    coverage: History,
    days: list[Day],
    readings: Iterable[tuple[datetime, str]],
    no_readings: Iterable[datetime],
    pending_readings: Iterable[datetime] = (),
    decommission: tuple[datetime, str] | None = None,
    config_at: Callable[[datetime], Config],
) -> Result:
    """Replay the sensor's lifecycle up to `now`.

    readings          (taken_at, evidence id) of accepted readings, any gateway
    no_readings       finished_at of no_readings outcomes from gateways available then
    pending_readings  finished_at of readings outcomes whose batch is still unresolved
    """
    r = Replay(created_at, coverage, config_at)
    readings = sorted(readings)
    no_readings = sorted(no_readings)
    pending_readings = list(pending_readings)
    changes = [(s.start, s.value) for s in coverage if s.start > created_at]
    di = ri = ci = 0

    while True:
        candidates = []
        if decommission is not None and r.state != DECOMMISSIONED and decommission[0] <= now:
            candidates.append((max(decommission[0], created_at), DECOMMISSION, "decommission"))
        if ci < len(changes) and changes[ci][0] <= now:
            candidates.append((changes[ci][0], COVERAGE, "coverage"))
        if ri < len(readings) and readings[ri][0] <= now:
            candidates.append((max(readings[ri][0], created_at), READING, "reading"))
        if di < len(days) and days[di].kind != UNRESOLVED and days[di].decided_at <= now:
            candidates.append((day_end(days[di].date), TIMER, "day"))
        due = r.timer_due()
        if due is not None and due <= now and not r.window_waits(due, pending_readings):
            candidates.append((due, TIMER, "timer"))
        if not candidates:
            break
        at, _, kind = min(candidates, key=lambda c: (c[0], c[1]))

        if kind == "decommission":
            r.move(at, DECOMMISSIONED, decommission[1], "decommission")
            decommission = None
        elif kind == "coverage":
            r.on_coverage(at, changes[ci][1])
            ci += 1
        elif kind == "reading":
            r.on_reading(at, readings[ri][1])
            ri += 1
        elif kind == "day":
            r.on_day(days[di])
            di += 1
        else:
            r.on_timer(at, no_readings)

    r.result.next_evaluation_at = r.next_evaluation(now)
    return r.result


class Replay:
    def __init__(self, created_at: datetime, coverage: History, config_at: Callable[[datetime], Config]):
        self.coverage = coverage
        self.config_at = config_at
        self.result = Result(lifecycle=PENDING, reason=None, since=created_at)
        self.current_coverage = value_at(coverage, created_at) or "none"
        self.last_reading_day: date | None = None
        self.wait_start: datetime | None = None  # start of the dormant wait or sampling window

    @property
    def state(self) -> str:
        return self.result.lifecycle

    def move(self, at: datetime, to: str, reason: str | None, rule: str, evidence_ids=()) -> None:
        res = self.result
        at = max(at, res.since)
        res.transitions.append(Transition(at, res.lifecycle, res.reason, to, reason, rule, tuple(evidence_ids)))
        res.lifecycle, res.reason, res.since = to, reason, at
        if to in (ACTIVE, PENDING):
            res.sampling_cycles_done = 0
        if to == PENDING:
            res.quiet_checked_days = 0
        self.wait_start = at if to in (DORMANT, SAMPLING) else None

    # Events

    def on_coverage(self, at: datetime, value: str) -> None:
        previous, self.current_coverage = self.current_coverage, value
        if value == "none":
            if self.state not in (PENDING, DECOMMISSIONED):
                self.move(at, RETIRED, NO_LIVE_COVERAGE, "no_live_coverage")
        elif previous == "none" and self.state == RETIRED and self.result.reason == NO_LIVE_COVERAGE:
            self.move(at, PENDING, None, "coverage_regained")

    def on_reading(self, at: datetime, evidence_id: str) -> None:
        self.last_reading_day = max(self.last_reading_day or utc_date(at), utc_date(at))
        if self.current_coverage == "none" or self.state == DECOMMISSIONED:
            return
        if self.state == PENDING:
            self.move(at, ACTIVE, None, "first_reading", [evidence_id])
        elif self.state in (DORMANT, SAMPLING) or (self.state == RETIRED and self.result.reason == NO_READINGS):
            self.move(at, ACTIVE, None, "reading", [evidence_id])
        if self.state == ACTIVE:
            self.result.quiet_checked_days = 0

    def on_day(self, day: Day) -> None:
        if self.state != ACTIVE or day.kind != QUIET:
            return
        if self.last_reading_day is not None and day.date <= self.last_reading_day:
            return  # only quiet days after the last reading day count
        self.result.quiet_checked_days += 1
        end = day_end(day.date)
        if self.result.quiet_checked_days >= self.config_at(end).quiet_days_before_dormant:
            self.move(end, DORMANT, None, "quiet_days")

    def timer_due(self) -> datetime | None:
        if self.state == DORMANT:
            return add_available(self.coverage, self.wait_start, self.config_at(self.wait_start).dormant_wait)
        if self.state == SAMPLING:
            return add_available(self.coverage, self.wait_start, self.config_at(self.wait_start).sampling_window)
        return None

    def window_waits(self, end: datetime, pending_readings: list[datetime]) -> bool:
        """A window's evaluation waits while a readings outcome inside it is unresolved."""
        return self.state == SAMPLING and any(self.wait_start <= t < end for t in pending_readings)

    def on_timer(self, at: datetime, no_readings: list[datetime]) -> None:
        if self.state == DORMANT:
            self.move(at, SAMPLING, None, "dormant_wait_elapsed")
            return
        checked = any(self.wait_start <= t < at for t in no_readings)
        if not checked:
            self.move(at, SAMPLING, None, "window_without_checks")  # a new window, not a cycle
            return
        self.result.sampling_cycles_done += 1
        if self.result.sampling_cycles_done >= self.config_at(at).sampling_cycles_before_retired:
            self.move(at, RETIRED, NO_READINGS, "sampling_cycles_done")
        else:
            self.move(at, DORMANT, None, "window_without_readings")

    def next_evaluation(self, now: datetime) -> datetime | None:
        if self.state == DORMANT:
            wait = self.config_at(self.wait_start).dormant_wait
        elif self.state == SAMPLING:
            wait = self.config_at(self.wait_start).sampling_window
        else:
            return None
        return next_evaluation_at(self.coverage, self.wait_start, wait, now)
