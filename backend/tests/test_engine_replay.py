"""Pure tests for the lifecycle replay, including the brief's worked example. No database."""

from dataclasses import replace
from datetime import timedelta

from core.config import DEFAULT
from sensors.engine.availability import history
from sensors.engine.days import Outcome, classify_days
from sensors.engine.replay import Transition, replay
from tests.conftest import at

H = timedelta(hours=1)


def always(gateway_id, when):
    return True


def run(
    now,
    *,
    readings=((0, 12),),
    quiet_days=range(1, 49),
    coverage=None,
    outcomes=(),
    batches=None,
    available=always,
    no_readings=None,
    pending=(),
    decommission=None,
    config=DEFAULT,
    created=None,
):
    """Sensor S covered by G, which reports no_readings at 12:00 on `quiet_days`."""
    created = created or at(0)
    outcomes = [Outcome("G", at(n, 12), "no_readings") for n in quiet_days] + list(outcomes)
    outcomes = [o for o in outcomes if o.finished_at <= now]
    reading_list = [(at(*r), f"r{i}") for i, r in enumerate(readings) if at(*r) <= now]
    days = classify_days(
        created.date(),
        readings=[t for t, _ in reading_list],
        outcomes=outcomes,
        batches=batches or {},
        available=available,
        now=now,
    )
    if no_readings is None:
        no_readings = [o.finished_at for o in outcomes if o.outcome == "no_readings" and available("G", o.finished_at)]
    return replay(
        created_at=created,
        now=now,
        coverage=coverage or history("available", created, []),
        days=days,
        readings=reading_list,
        no_readings=no_readings,
        pending_readings=pending,
        decommission=decommission,
        config_at=lambda t: config,
    )


def states(result):
    return [(t.to_state, t.to_reason, t.at) for t in result.transitions]


class TestWorkedExample:
    """Brief: G reports S once a day at 12:00. Day 0 readings, then no_readings every day."""

    def test_day_0_reading_makes_it_active(self):
        r = run(at(0, 13))
        assert (r.lifecycle, r.since, r.quiet_checked_days) == ("active", at(0, 12), 0)
        assert r.transitions == [Transition(at(0, 12), "pending", None, "active", None, "first_reading", ("r0",))]

    def test_quiet_days_count_as_each_day_completes(self):
        for n in range(1, 15):
            r = run(at(n + 1) - timedelta(seconds=1))
            assert r.quiet_checked_days == n - 1
            r = run(at(n + 1))
            assert (r.lifecycle, r.quiet_checked_days) == ("active" if n < 14 else "dormant", n)

    def test_dormant_when_day_14_completes(self):
        r = run(at(15))
        assert (r.lifecycle, r.since, r.next_evaluation_at) == ("dormant", at(15), at(29))

    def test_sampling_after_14_days_of_available_time(self):
        r = run(at(29))
        assert (r.lifecycle, r.since, r.next_evaluation_at) == ("sampling", at(29), at(32))

    def test_window_ends_with_checks_and_no_reading(self):
        r = run(at(32))
        assert (r.lifecycle, r.sampling_cycles_done, r.next_evaluation_at) == ("dormant", 1, at(46))

    def test_the_wait_ends_again(self):
        r = run(at(46))
        assert (r.lifecycle, r.sampling_cycles_done, r.next_evaluation_at) == ("sampling", 1, at(49))

    def test_second_window_retires_it(self):
        r = run(at(49))
        assert (r.lifecycle, r.reason, r.since, r.sampling_cycles_done) == ("retired", "no_readings", at(49), 2)
        assert r.next_evaluation_at is None
        assert states(r) == [
            ("active", None, at(0, 12)),
            ("dormant", None, at(15)),
            ("sampling", None, at(29)),
            ("dormant", None, at(32)),
            ("sampling", None, at(46)),
            ("retired", "no_readings", at(49)),
        ]

    def test_one_replay_at_the_end_equals_stepping_through(self):
        # A jump from day 0 to day 60 produces every transition at its own time.
        assert states(run(at(60))) == states(run(at(49)))


class TestVariationDisconnectionMidWindow:
    """G reports auth_failed day 30 12:00 and a good cycle day 37 12:00."""

    coverage = history("available", at(0), [(at(30, 12), "recoverable"), (at(37, 12), "available")])

    def available(self, gw, when):
        return not (at(30, 12) <= when < at(37, 12))

    def go(self, now):
        quiet = [n for n in range(1, 49) if not 30 <= n <= 36]
        return run(now, coverage=self.coverage, available=self.available, quiet_days=quiet)

    def test_window_pauses_with_36_hours_left(self):
        r = self.go(at(33))
        assert (r.lifecycle, r.next_evaluation_at) == ("sampling", None)

    def test_window_resumes_and_ends_on_day_39(self):
        r = self.go(at(37, 13))
        assert (r.lifecycle, r.next_evaluation_at) == ("sampling", at(39))
        r = self.go(at(39))
        assert (r.lifecycle, r.since, r.sampling_cycles_done) == ("dormant", at(39), 1)

    def test_stays_sampling_throughout(self):
        r = self.go(at(38, 23))
        assert states(r)[-1] == ("sampling", None, at(29))


class TestVariationLateReading:
    """On day 20, G uploads a batch holding a reading taken on day 9."""

    def test_without_it_the_sensor_is_dormant(self):
        assert run(at(20)).lifecycle == "dormant"

    def test_with_it_days_10_to_19_are_10_quiet_days_so_active(self):
        r = run(at(20), readings=[(0, 12), (9, 8)])
        assert (r.lifecycle, r.quiet_checked_days, r.since) == ("active", 10, at(0, 12))
        assert states(r) == [("active", None, at(0, 12))]

    def test_it_moves_every_later_timer(self):
        r = run(at(24), readings=[(0, 12), (9, 8)])
        assert (r.lifecycle, r.since, r.next_evaluation_at) == ("dormant", at(24), at(38))


class TestVariationUnresolvedDay:
    """On day 14, G reports readings but the batch never arrives."""

    def go(self, now):
        lost = Outcome("G", at(14, 12), "readings", "lost")
        return run(now, quiet_days=[n for n in range(1, 49) if n != 14], outcomes=[lost])

    def test_day_14_blocks_while_unresolved(self):
        r = self.go(at(15, 11))
        assert (r.lifecycle, r.quiet_checked_days) == ("active", 13)

    def test_unchecked_once_resolved_at_day_15_noon(self):
        r = self.go(at(15, 12))
        assert (r.lifecycle, r.quiet_checked_days) == ("active", 13)

    def test_dormant_after_another_quiet_day_on_day_16(self):
        r = self.go(at(16))
        assert (r.lifecycle, r.since, r.quiet_checked_days) == ("dormant", at(16), 14)


class TestCoverage:
    def test_loss_retires_with_no_live_coverage_at_once(self):
        coverage = history("available", at(0), [(at(5, 9), "none")])
        r = run(at(10), coverage=coverage)
        assert (r.lifecycle, r.reason, r.since) == ("retired", "no_live_coverage", at(5, 9))

    def test_pending_stays_pending(self):
        coverage = history("available", at(0), [(at(0, 6), "none")])
        r = run(at(10), coverage=coverage)
        assert (r.lifecycle, r.transitions) == ("pending", [])

    def test_readings_under_none_do_not_wake_it(self):
        coverage = history("none", at(0), [])
        assert run(at(10), coverage=coverage).lifecycle == "pending"

    def test_regaining_coverage_makes_it_pending_with_counters_reset(self):
        coverage = history("available", at(0), [(at(5), "none"), (at(7), "recoverable")])
        r = run(at(10), coverage=coverage)
        assert (r.lifecycle, r.reason, r.since) == ("pending", None, at(7))
        assert (r.quiet_checked_days, r.sampling_cycles_done) == (0, 0)

    def test_retired_no_readings_loses_coverage_too(self):
        coverage = history("available", at(0), [(at(50), "none")])
        r = run(at(51), coverage=coverage)
        assert (r.lifecycle, r.reason) == ("retired", "no_live_coverage")

    def test_readings_wake_under_stopped_or_recoverable_coverage(self):
        coverage = history("available", at(0), [(at(16), "stopped")])
        r = run(at(20), coverage=coverage, readings=[(0, 12), (18, 9)])
        assert (r.lifecycle, r.since) == ("active", at(18, 9))

    def test_dormant_wait_pauses_while_not_available(self):
        coverage = history("available", at(0), [(at(20), "recoverable"), (at(25), "available")])
        r = run(at(30), coverage=coverage)
        assert (r.lifecycle, r.next_evaluation_at) == ("dormant", at(34))


class TestReadingsWake:
    def test_dormant(self):
        r = run(at(20), readings=[(0, 12), (17, 3)])
        assert states(r)[-1] == ("active", None, at(17, 3))
        assert r.quiet_checked_days == 2  # days 18 and 19

    def test_sampling(self):
        r = run(at(31), readings=[(0, 12), (30, 3)])
        assert (r.lifecycle, r.since, r.sampling_cycles_done) == ("active", at(30, 3), 0)

    def test_retired_no_readings(self):
        r = run(at(52), readings=[(0, 12), (50, 3)])
        assert (r.lifecycle, r.reason, r.since) == ("active", None, at(50, 3))

    def test_reading_day_resets_the_quiet_count(self):
        r = run(at(12), readings=[(0, 12), (8, 6)])
        assert r.quiet_checked_days == 3  # days 9, 10, 11


class TestSamplingWindows:
    def test_window_without_checks_starts_a_new_window_and_is_not_a_cycle(self):
        quiet = [n for n in range(1, 49) if not 29 <= n <= 31]
        r = run(at(34), quiet_days=quiet)
        assert (r.lifecycle, r.since, r.sampling_cycles_done, r.next_evaluation_at) == ("sampling", at(32), 0, at(35))
        assert states(r)[-2:] == [("sampling", None, at(29)), ("sampling", None, at(32))]
        # The second window has checks (days 32-34): that one is a cycle.
        r = run(at(35), quiet_days=quiet)
        assert (r.lifecycle, r.sampling_cycles_done) == ("dormant", 1)

    def test_window_waits_for_an_unresolved_readings_outcome_inside_it(self):
        r = run(at(33), pending=[at(31, 12)])
        assert (r.lifecycle, r.since) == ("sampling", at(29))


class TestDecommission:
    def test_terminal(self):
        r = run(at(60), decommission=(at(10), "broken"))
        assert (r.lifecycle, r.reason, r.since) == ("decommissioned", "broken", at(10))
        assert states(r)[-1] == ("decommissioned", "broken", at(10))

    def test_wins_over_a_reading_at_the_same_instant(self):
        r = run(at(20), readings=[(0, 12), (17, 3)], decommission=(at(17, 3), "broken"))
        assert r.lifecycle == "decommissioned"

    def test_pending_can_be_decommissioned(self):
        r = run(at(1), readings=(), decommission=(at(0, 1), "never installed"))
        assert (r.lifecycle, r.reason) == ("decommissioned", "never installed")


class TestConfiguration:
    def test_thresholds_come_from_the_config(self):
        config = replace(DEFAULT, quiet_days_before_dormant=3, dormant_wait=2 * 24 * H, sampling_window=24 * H)
        r = run(at(10), config=config)
        assert states(r)[:4] == [
            ("active", None, at(0, 12)),
            ("dormant", None, at(4)),
            ("sampling", None, at(6)),
            ("dormant", None, at(7)),
        ]
