"""Pure unit tests for coverage histories and available time. No database."""

from datetime import timedelta

from sensors.engine.availability import (
    Segment,
    add_available,
    availability,
    available_between,
    gateway_class_history,
    history,
    next_evaluation_at,
    value_at,
)
from tests.conftest import at

H = timedelta(hours=1)


class TestHistory:
    def test_segments_from_changes(self):
        h = history("none", at(0), [(at(1), "available"), (at(3), "recoverable")])
        assert h == [
            Segment(at(0), at(1), "none"),
            Segment(at(1), at(3), "available"),
            Segment(at(3), None, "recoverable"),
        ]

    def test_repeated_value_is_ignored(self):
        h = history("none", at(0), [(at(1), "available"), (at(2), "available")])
        assert h == [Segment(at(0), at(1), "none"), Segment(at(1), None, "available")]

    def test_change_at_the_start_replaces_the_initial_value(self):
        assert history("none", at(0), [(at(0), "available")]) == [Segment(at(0), None, "available")]

    def test_value_at(self):
        h = history("none", at(0), [(at(1), "available")])
        assert [value_at(h, t) for t in (at(-1), at(0), at(0, 23), at(1), at(9))] == [
            None,
            "none",
            "none",
            "available",
            "available",
        ]


class TestGatewayClassHistory:
    def test_combines_status_and_command_state(self):
        h = gateway_class_history(
            at(0),
            status_changes=[(at(1), "connected"), (at(5), "stale")],
            command_changes=[(at(2), "stop_pending"), (at(3), "stopped"), (at(4), "resume_pending")],
        )
        assert [(s.start, s.value) for s in h] == [
            (at(0), "recoverable"),  # new
            (at(1), "available"),  # connected, running
            (at(3), "stopped"),  # connected, stopped (stop_pending is still available)
            (at(5), "recoverable"),  # stale, whatever the command state
        ]

    def test_availability_for_day_classification(self):
        histories = {"g1": gateway_class_history(at(0), [(at(1), "connected"), (at(2), "suspended")], [])}
        available = availability(histories)
        assert [available("g1", t) for t in (at(0, 12), at(1, 12), at(2, 12))] == [False, True, False]
        assert available("unknown", at(1, 12)) is False


class TestAvailableTime:
    h = history("none", at(0), [(at(1), "available"), (at(2), "stopped"), (at(3), "available")])

    def test_available_between(self):
        assert available_between(self.h, at(0), at(5)) == 3 * timedelta(days=1)
        assert available_between(self.h, at(1, 12), at(3, 6)) == 18 * H

    def test_add_available_skips_unavailable_time(self):
        assert add_available(self.h, at(1), 24 * H) == at(2)
        assert add_available(self.h, at(1), 30 * H) == at(3, 6)
        assert add_available(self.h, at(1, 12), 12 * H) == at(2)

    def test_starting_while_paused_waits_for_coverage(self):
        assert add_available(self.h, at(0), 6 * H) == at(1, 6)

    def test_unreachable_while_coverage_stays_unavailable(self):
        h = history("available", at(0), [(at(1), "recoverable")])
        assert add_available(h, at(0), 36 * H) is None

    def test_next_evaluation_at_is_null_while_paused(self):
        assert next_evaluation_at(self.h, at(1), 30 * H, now=at(2, 12)) is None
        assert next_evaluation_at(self.h, at(1), 30 * H, now=at(3, 1)) == at(3, 6)

    def test_worked_example_disconnection_mid_window(self):
        """Window from day 29, 72h of available time. auth_failed day 30 12:00, good cycle day 37 12:00."""
        h = history("available", at(0), [(at(30, 12), "recoverable"), (at(37, 12), "available")])
        assert available_between(h, at(29), at(30, 12)) == 36 * H
        assert next_evaluation_at(h, at(29), 72 * H, now=at(33)) is None
        assert next_evaluation_at(h, at(29), 72 * H, now=at(37, 12)) == at(39)
        # Before the disconnection was known, the window was due at day 32.
        before = history("available", at(0), [])
        assert next_evaluation_at(before, at(29), 72 * H, now=at(30)) == at(32)
