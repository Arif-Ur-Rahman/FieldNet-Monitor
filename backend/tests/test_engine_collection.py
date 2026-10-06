"""Pure unit tests for the latest collection rule. No database."""

import pytest

from sensors.engine.collection import Collection, latest_collection
from sensors.engine.days import BatchInfo, Outcome
from tests.conftest import at

NOW = at(10, 12)


def run(outcomes=(), *, coverage="available", classes=None, batches=None, unmentioned=(), now=NOW):
    return latest_collection(
        now=now,
        coverage=coverage,
        gateway_classes=classes if classes is not None else {"g1": "available", "g2": "available"},
        outcomes=outcomes,
        batches=batches or {},
        unmentioned_readings=unmentioned,
    )


def o(outcome, hour=10, gw="g1", day=10, batch_id=None):
    if outcome == "readings" and batch_id is None:
        batch_id = "b1"
    return Outcome(gw, at(day, hour), outcome, batch_id)


ARRIVED = {"b1": BatchInfo(received_at=at(10, 10, 1), resolved_at=at(10, 10, 2))}


class TestCoverage:
    def test_stopped_coverage_is_collection_stopped(self):
        assert run([o("no_readings")], coverage="stopped") == Collection("collection_stopped", None)

    @pytest.mark.parametrize("coverage", ["recoverable", "none"])
    def test_other_coverage_is_not_checked(self, coverage):
        assert run([o("no_readings")], coverage=coverage) == Collection("not_checked", None)

    def test_available_with_nothing_qualifying_is_not_checked(self):
        assert run([]) == Collection("not_checked", None)


class TestLatestPerGateway:
    @pytest.mark.parametrize("outcome", ["readings", "no_readings", "could_not_read", "timed_out"])
    def test_single_outcome(self, outcome):
        assert run([o(outcome)], batches=ARRIVED).value == outcome

    def test_only_the_most_recent_outcome_of_a_gateway_counts(self):
        assert run([o("readings", 8), o("timed_out", 10)], batches=ARRIVED).value == "timed_out"

    def test_older_than_24_hours_does_not_count(self):
        assert run([o("no_readings", 11, day=9)]).value == "not_checked"
        assert run([o("no_readings", 12, day=9)]).value == "no_readings"

    def test_only_available_gateways_count(self):
        classes = {"g1": "recoverable", "g2": "available"}
        outcomes = [o("readings", gw="g1"), o("timed_out", gw="g2")]
        assert run(outcomes, classes=classes, batches=ARRIVED).value == "timed_out"

    def test_outcomes_after_now_are_ignored(self):
        assert run([o("no_readings", 13)]).value == "not_checked"

    def test_same_instant_ties_go_by_precedence(self):
        assert run([o("timed_out", 10), o("no_readings", 10)]).value == "no_readings"


class TestPrecedenceAcrossGateways:
    @pytest.mark.parametrize(
        ("g1", "g2", "expected"),
        [
            ("readings", "no_readings", "readings"),
            ("no_readings", "could_not_read", "no_readings"),
            ("could_not_read", "timed_out", "could_not_read"),
            ("timed_out", "timed_out", "timed_out"),
        ],
    )
    def test_best_outcome_wins(self, g1, g2, expected):
        outcomes = [o(g1, 9, gw="g1"), o(g2, 10, gw="g2")]
        assert run(outcomes, batches=ARRIVED).value == expected


class TestBatches:
    def test_unresolved_batch_shows_readings_and_flips_at_the_deadline(self):
        c = run([o("readings", 10)])
        assert c == Collection("readings", at(11, 10))

    def test_missing_batch_after_the_deadline_is_could_not_read(self):
        c = run([o("readings", 12, day=9), o("timed_out", 13, day=9, gw="g2")])
        assert c.value == "could_not_read"

    def test_quarantined_batch_is_could_not_read(self):
        batches = {"b1": BatchInfo(received_at=at(10, 10, 1), resolved_at=at(10, 10, 2), quarantined=True)}
        assert run([o("readings")], batches=batches).value == "could_not_read"


class TestUnmentionedReadings:
    def test_count_as_a_readings_outcome_from_their_gateway(self):
        assert run([o("no_readings", 9)], unmentioned=[("g1", at(10, 10))]).value == "readings"

    def test_timed_at_taken_at(self):
        assert run([o("no_readings", 11)], unmentioned=[("g1", at(10, 10))]).value == "no_readings"

    def test_from_an_unavailable_gateway_do_not_count(self):
        classes = {"g1": "available", "g9": "recoverable"}
        assert run([], classes=classes, unmentioned=[("g9", at(10, 10))]).value == "not_checked"

    def test_never_turn_into_could_not_read(self):
        # Exactly 24h old: still inside the window, and never treated as a missing batch.
        assert run([], unmentioned=[("g1", at(9, 12))]).value == "readings"


class TestChangesAt:
    def test_when_the_freshest_outcome_ages_out(self):
        c = run([o("no_readings", 9, gw="g1"), o("timed_out", 11, gw="g2")])
        assert c == Collection("no_readings", at(11, 9))

    def test_nothing_changes_without_fresh_outcomes(self):
        assert run([]).changes_at is None
