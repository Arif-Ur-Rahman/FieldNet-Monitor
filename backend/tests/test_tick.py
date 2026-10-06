import pytest
from django.core.management import call_command

from core import clock, tick
from core.models import ClockState
from gateways.models import Gateway
from testing import faults
from tests.conftest import at
from tests.helpers import register_gateway

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


class FakeTimers:
    """A due-work source backed by a list of (due_at, label). Running an item removes it."""

    def __init__(self, name):
        self.name = name
        self.pending = []
        self.ran = []  # (label, effective_at, server clock while running)

    def add(self, due_at, label, then=None):
        self.pending.append((due_at, label, then))

    def __call__(self, up_to):
        due = sorted((item for item in self.pending if item[0] <= up_to), key=lambda item: item[0])
        if not due:
            return None
        item = due[0]

        def run(effective_at):
            self.pending.remove(item)
            self.ran.append((item[1], effective_at, clock.now()))
            if item[2]:
                item[2](self)

        return tick.Due(due_at=item[0], run=run, label=item[1])


@pytest.fixture
def timers():
    """Two fake sources, registered as 'first' then 'second'."""
    sources = FakeTimers("first"), FakeTimers("second")
    for source in sources:
        tick.register(source.name, source)
    yield sources
    for source in sources:
        tick.unregister(source.name)


def merged(*sources):
    return sorted((r for s in sources for r in s.ran), key=lambda r: r[1])


class TestTick:
    def test_runs_nothing_when_nothing_is_due(self, test_mode, timers):
        timers[0].add(at(3), "later")
        assert tick.tick(at(2)) == 0
        assert timers[0].ran == []

    def test_runs_due_items_in_due_order_across_sources(self, test_mode, timers):
        first, second = timers
        first.add(at(3), "a3")
        second.add(at(1), "b1")
        first.add(at(2), "a2")
        assert tick.tick(at(5)) == 3
        assert [label for label, *_ in merged(first, second)] == ["b1", "a2", "a3"]

    def test_equal_due_times_run_in_registration_order(self, test_mode, timers):
        first, second = timers
        second.add(at(1), "second")
        first.add(at(1), "first")
        tick.tick(at(1))
        assert [label for label, *_ in first.ran + second.ran] == ["first", "second"]
        assert first.ran[0][1] == second.ran[0][1] == at(1)

    def test_work_scheduled_while_running_runs_in_the_same_tick(self, test_mode, timers):
        first, _ = timers
        first.add(at(1), "attempt 1", then=lambda s: s.add(at(1, 0, 1), "attempt 2"))
        tick.tick(at(1, 1))
        assert [(label, eff) for label, eff, _ in first.ran] == [("attempt 1", at(1)), ("attempt 2", at(1, 0, 1))]

    def test_a_failing_item_rolls_back_and_raises(self, test_mode, api, timers):
        first, _ = timers

        def boom(source):
            Gateway.objects.update(name="changed")
            raise RuntimeError("boom")

        register_gateway(api)
        first.add(at(1), "boom", then=boom)
        with pytest.raises(RuntimeError):
            tick.tick(at(1))
        assert Gateway.objects.get().name == "Gateway 1"


class TestClockEndpoint:
    def test_jump_applies_each_item_at_its_own_due_time(self, test_mode, api, timers):
        first, second = timers
        api.post("/test/clock", {"now": iso(0)}, format="json")
        first.add(at(1, 12), "day 1")
        second.add(at(3), "day 3")
        resp = api.post("/test/clock", {"now": iso(5)}, format="json")
        assert resp.status_code == 200
        assert resp.json() == {"now": iso(5)}
        # effective_at is the due time; the server clock while running is the jump target.
        assert merged(first, second) == [("day 1", at(1, 12), at(5)), ("day 3", at(3), at(5))]

    def test_items_after_the_new_time_wait(self, test_mode, api, timers):
        first, _ = timers
        first.add(at(6), "day 6")
        api.post("/test/clock", {"now": iso(5)}, format="json")
        assert first.ran == []
        api.post("/test/clock", {"now": iso(6)}, format="json")
        assert [label for label, *_ in first.ran] == ["day 6"]

    def test_backwards_is_409_and_runs_nothing(self, test_mode, api, timers):
        first, _ = timers
        api.post("/test/clock", {"now": iso(5)}, format="json")
        first.add(at(4), "day 4")
        resp = api.post("/test/clock", {"now": iso(4)}, format="json")
        assert resp.status_code == 409
        assert resp.json()["error"] == "clock_backwards"
        assert first.ran == []
        assert clock.now() == at(5)

    @pytest.mark.parametrize("body", [{}, {"now": "yesterday"}, {"now": None}])
    def test_invalid_body_is_422(self, test_mode, api, body):
        assert api.post("/test/clock", body, format="json").status_code == 422


class TestDrainEndpoint:
    def test_runs_due_work_without_moving_the_clock(self, test_mode, api, timers):
        first, _ = timers
        api.post("/test/clock", {"now": iso(5)}, format="json")
        first.add(at(4), "day 4")
        first.add(at(6), "day 6")
        resp = api.post("/test/drain")
        assert resp.status_code == 200
        assert resp.json() == {"now": iso(5)}
        assert [(label, eff) for label, eff, _ in first.ran] == [("day 4", at(4))]
        assert clock.now() == at(5)


class TestResetEndpoint:
    def test_empties_every_table_including_the_clock(self, test_mode, api):
        api.post("/test/clock", {"now": iso(5)}, format="json")
        register_gateway(api)
        faults.set_processing_failures(3)
        assert api.post("/test/reset").status_code == 204
        assert not Gateway.objects.exists()
        assert not ClockState.objects.exists()
        assert faults.take_processing_failure() is False
        # The clock accepts any time again, and the same gateway id registers again.
        assert api.post("/test/clock", {"now": iso(1)}, format="json").status_code == 200
        register_gateway(api)


class TestFaults:
    def test_endpoint_sets_how_many_attempts_fail(self, test_mode, api):
        assert api.post("/test/faults", {"processing_failures": 2}, format="json").status_code == 204
        assert [faults.take_processing_failure() for _ in range(3)] == [True, True, False]

    def test_setting_again_replaces_the_count(self, test_mode, api):
        api.post("/test/faults", {"processing_failures": 5}, format="json")
        api.post("/test/faults", {"processing_failures": 1}, format="json")
        assert [faults.take_processing_failure() for _ in range(2)] == [True, False]

    @pytest.mark.parametrize("body", [{}, {"processing_failures": -1}, {"processing_failures": "two"}])
    def test_invalid_body_is_422(self, test_mode, api, body):
        assert api.post("/test/faults", body, format="json").status_code == 422

    def test_never_fires_outside_test_mode(self, settings):
        faults.set_processing_failures(1)
        settings.TEST_MODE = False
        assert faults.take_processing_failure() is False


@pytest.mark.parametrize("path", ["/test/reset", "/test/clock", "/test/drain", "/test/faults"])
def test_routes_are_404_outside_test_mode(settings, api, path):
    settings.TEST_MODE = False
    resp = api.post(path, {"now": iso(1), "processing_failures": 1}, format="json")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


class TestWorker:
    @pytest.fixture(autouse=True)
    def keep_test_connection(self, monkeypatch):
        # The worker drops stale connections each pass; inside a test transaction that would close it.
        monkeypatch.setattr("core.management.commands.run_worker.close_old_connections", lambda: None)

    def test_one_pass_runs_due_work_on_the_wall_clock(self, settings, timers):
        settings.TEST_MODE = False
        first, _ = timers
        first.add(at(1), "due long ago")
        call_command("run_worker", "--once")
        assert [(label, eff) for label, eff, _ in first.ran] == [("due long ago", at(1))]

    def test_a_failing_pass_is_logged_not_raised(self, settings, timers, caplog):
        settings.TEST_MODE = False
        first, _ = timers
        first.add(at(1), "boom", then=lambda s: 1 / 0)
        call_command("run_worker", "--once")
        assert "Worker pass failed" in caplog.text

    def test_idles_in_test_mode(self, test_mode, timers):
        first, _ = timers
        first.add(at(1), "due")
        call_command("run_worker", "--once")
        assert first.ran == []


def test_lower_order_runs_first_on_ties_whatever_the_registration_order(test_mode):
    late, early = FakeTimers("late"), FakeTimers("early")
    tick.register("late", late, order=50)
    tick.register("early", early, order=5)
    try:
        late.add(at(1), "late")
        early.add(at(1), "early")
        ran = []
        late.ran, early.ran = ran, ran
        tick.tick(at(1))
        assert [label for label, *_ in ran] == ["early", "late"]
    finally:
        tick.unregister("late")
        tick.unregister("early")
