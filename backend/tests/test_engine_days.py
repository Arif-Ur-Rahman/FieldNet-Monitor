"""Pure unit tests for sensor day classification. No database."""

from datetime import timedelta

from sensors.engine.days import QUIET, READING, UNCHECKED, UNRESOLVED, BatchInfo, Day, Outcome, classify, classify_days
from tests.conftest import at


def always(gateway_id, when):
    return True


def never(gateway_id, when):
    return False


def day(n):
    return at(n).date()


def run(n, *, readings=(), outcomes=(), batches=None, available=always, now=None):
    return classify(
        day(n),
        readings=readings,
        outcomes=outcomes,
        batches=batches or {},
        available=available,
        now=now or at(n + 10),
    )


def quiet(n, gw="g1"):
    return Outcome(gw, at(n, 12), "no_readings")


def readings_outcome(n, batch_id="b1", gw="g1"):
    return Outcome(gw, at(n, 12), "readings", batch_id)


class TestRules:
    def test_reading_day(self):
        assert run(3, readings=[at(3, 8)]) == Day(day(3), READING, at(4))

    def test_reading_from_another_day_does_not_count(self):
        assert run(3, readings=[at(2, 23, 59), at(4)]).kind == UNCHECKED

    def test_quiet_day(self):
        assert run(3, outcomes=[quiet(3)]) == Day(day(3), QUIET, at(4))

    def test_quiet_needs_an_available_gateway_at_finished_at(self):
        seen = []

        def available(gw, when):
            seen.append((gw, when))
            return False

        assert run(3, outcomes=[quiet(3)], available=available).kind == UNCHECKED
        assert seen == [("g1", at(3, 12))]

    def test_one_available_gateway_is_enough(self):
        outcomes = [quiet(3, "down"), quiet(3, "up")]
        assert run(3, outcomes=outcomes, available=lambda gw, t: gw == "up").kind == QUIET

    def test_silence_is_unchecked(self):
        assert run(3) == Day(day(3), UNCHECKED, at(4))

    def test_could_not_read_and_timed_out_are_unchecked(self):
        outcomes = [Outcome("g1", at(3, 1), "could_not_read"), Outcome("g1", at(3, 2), "timed_out")]
        assert run(3, outcomes=outcomes).kind == UNCHECKED


class TestFirstMatchWins:
    def test_reading_beats_unresolved(self):
        assert run(3, readings=[at(3, 1)], outcomes=[readings_outcome(3)], now=at(4)).kind == READING

    def test_unresolved_beats_quiet(self):
        assert run(3, outcomes=[readings_outcome(3), quiet(3)], now=at(4)).kind == UNRESOLVED

    def test_quiet_beats_unchecked(self):
        outcomes = [Outcome("g1", at(3, 1), "timed_out"), quiet(3)]
        assert run(3, outcomes=outcomes).kind == QUIET


class TestBatchResolution:
    def test_unarrived_batch_is_unresolved_until_the_deadline(self):
        d = run(3, outcomes=[readings_outcome(3), quiet(3)], now=at(4, 11))
        assert d == Day(day(3), UNRESOLVED, at(4, 12))

    def test_missing_batch_becomes_could_not_read_at_the_deadline(self):
        d = run(3, outcomes=[readings_outcome(3)], now=at(4, 12))
        assert d == Day(day(3), UNCHECKED, at(4, 12))

    def test_missing_batch_with_a_quiet_outcome_is_quiet_once_resolved(self):
        d = run(3, outcomes=[readings_outcome(3), quiet(3)], now=at(5))
        assert d == Day(day(3), QUIET, at(4, 12))

    def test_processed_batch_resolves_at_its_processed_time(self):
        batches = {"b1": BatchInfo(received_at=at(3, 13), resolved_at=at(3, 13, 1))}
        d = run(3, outcomes=[readings_outcome(3), quiet(3)], batches=batches)
        # Resolved before the day ended: decided at the end of the day.
        assert d == Day(day(3), QUIET, at(4))

    def test_batch_processed_after_the_day_ends_decides_it_then(self):
        batches = {"b1": BatchInfo(received_at=at(4, 2), resolved_at=at(4, 3))}
        d = run(3, outcomes=[readings_outcome(3), quiet(3)], batches=batches)
        assert d == Day(day(3), QUIET, at(4, 3))

    def test_received_but_still_processing_is_unresolved_with_no_known_end(self):
        batches = {"b1": BatchInfo(received_at=at(3, 13), resolved_at=None)}
        assert run(3, outcomes=[readings_outcome(3)], batches=batches) == Day(day(3), UNRESOLVED, None)

    def test_batch_not_yet_processed_at_now_is_unresolved(self):
        batches = {"b1": BatchInfo(received_at=at(3, 13), resolved_at=at(4, 1))}
        assert run(3, outcomes=[readings_outcome(3)], batches=batches, now=at(4)).kind == UNRESOLVED

    def test_quarantined_batch_is_could_not_read(self):
        batches = {"b1": BatchInfo(received_at=at(3, 13), resolved_at=at(3, 14), quarantined=True)}
        assert run(3, outcomes=[readings_outcome(3)], batches=batches).kind == UNCHECKED

    def test_processed_batch_whose_readings_are_on_another_day_does_not_make_a_reading_day(self):
        batches = {"b1": BatchInfo(received_at=at(3, 13), resolved_at=at(3, 14))}
        assert run(3, readings=[at(2, 9)], outcomes=[readings_outcome(3)], batches=batches).kind == UNCHECKED

    def test_batch_arriving_after_the_deadline_does_not_reopen_the_day(self):
        batches = {"b1": BatchInfo(received_at=at(4, 13), resolved_at=at(4, 14))}
        assert run(3, outcomes=[readings_outcome(3)], batches=batches) == Day(day(3), UNCHECKED, at(4, 12))

    def test_its_readings_still_make_a_reading_day(self):
        batches = {"b1": BatchInfo(received_at=at(4, 13), resolved_at=at(4, 14))}
        assert run(3, readings=[at(3, 11)], outcomes=[readings_outcome(3)], batches=batches).kind == READING

    def test_custom_deadline(self):
        d = classify(
            day(3),
            readings=(),
            outcomes=[readings_outcome(3)],
            batches={},
            available=always,
            now=at(3, 18),
            deadline=timedelta(hours=6),
        )
        assert d == Day(day(3), UNCHECKED, at(4))


class TestClassifyDays:
    def test_only_complete_days(self):
        days = classify_days(day(0), readings=[at(0, 12)], outcomes=[], batches={}, available=always, now=at(2, 23))
        assert [(d.date, d.kind) for d in days] == [(day(0), READING), (day(1), UNCHECKED)]

    def test_a_day_is_complete_at_midnight(self):
        days = classify_days(day(0), readings=[], outcomes=[], batches={}, available=always, now=at(1))
        assert len(days) == 1

    def test_worked_example_unresolved_day(self):
        """Day 0 reading, days 1-13 quiet, day 14 readings with a batch that never arrives, day 15 quiet."""
        outcomes = [quiet(n) for n in range(1, 16) if n != 14] + [readings_outcome(14, "lost")]
        kwargs = dict(readings=[at(0, 12)], outcomes=outcomes, batches={}, available=always)

        before = classify_days(day(0), now=at(15, 11), **kwargs)
        assert before[14] == Day(day(14), UNRESOLVED, at(15, 12))

        after = classify_days(day(0), now=at(16), **kwargs)
        assert [d.kind for d in after] == [READING] + [QUIET] * 13 + [UNCHECKED, QUIET]
        assert after[14].decided_at == at(15, 12)
        assert after[15].decided_at == at(16)
