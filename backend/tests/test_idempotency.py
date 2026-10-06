"""Every write is safe to repeat: replays, concurrent duplicates, and two workers on the same due work."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection

from batches import processing
from batches.models import Batch, Reading
from core import timeline
from core.models import TimelineEntry
from gateways import commands
from gateways.models import Command, Cycle, CycleResult, Heartbeat
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


def snapshot():
    """Every row an effect could add."""
    return {
        "heartbeats": Heartbeat.objects.count(),
        "cycles": Cycle.objects.count(),
        "results": CycleResult.objects.count(),
        "batches": Batch.objects.count(),
        "readings": Reading.objects.count(),
        "commands": Command.objects.count(),
        "timeline": TimelineEntry.objects.count(),
    }


CYCLE = {
    "cycle_id": "c1",
    "started_at": iso(1, 11),
    "finished_at": iso(1, 11),
    "session": "ok",
    "results": [{"sensor_id": "s1", "outcome": "readings", "batch_id": "b1"}],
}
BATCH = {"sensor_id": "s1", "readings": [{"reading_id": "r1", "taken_at": iso(1, 11), "value": 1.0, "unit": "C"}]}


def setup_world(api, clock_at):
    clock_at(1, 12)
    token = register_gateway(api)
    register_sensor(api, "s1")
    set_coverage(api, "s1", ["g1"])
    return token


@pytest.mark.django_db
class TestReplays:
    """Gateways retry any non-2xx, so every gateway endpoint is sent twice and must change nothing the second time."""

    @pytest.fixture
    def gw(self, api, clock_at):
        return device(setup_world(api, clock_at))

    def test_heartbeat(self, gw):
        body = {"sent_at": iso(1, 12), "session": "auth_failed"}
        assert gw.post("/gw/v1/heartbeat", body, format="json").status_code == 204
        before = snapshot()
        assert gw.post("/gw/v1/heartbeat", body, format="json").status_code == 204
        assert snapshot() == before

    def test_cycle(self, gw):
        assert gw.post("/gw/v1/cycles", CYCLE, format="json").status_code == 202
        before = snapshot()
        assert gw.post("/gw/v1/cycles", CYCLE, format="json").status_code == 200
        assert snapshot() == before

    def test_batch_before_and_after_processing(self, gw, api):
        assert gw.put("/gw/v1/batches/b1", BATCH, format="json").status_code == 202
        before = snapshot()
        assert gw.put("/gw/v1/batches/b1", BATCH, format="json").status_code == 200
        assert snapshot() == before
        api.post("/test/drain")
        before = snapshot()
        assert gw.put("/gw/v1/batches/b1", BATCH, format="json").status_code == 200
        api.post("/test/drain")
        assert snapshot() == before

    def test_ack(self, gw, api):
        api.post("/api/v1/gateways/g1/actions", {"action": "stop"}, format="json")
        [command] = gw.get("/gw/v1/commands").json()["commands"]
        path = f"/gw/v1/commands/{command['command_id']}/ack"
        assert gw.post(path, {"acked_at": iso(1, 12)}, format="json").status_code == 204
        before = snapshot()
        assert gw.post(path, {"acked_at": iso(1, 12)}, format="json").status_code == 204
        assert snapshot() == before

    @pytest.mark.parametrize(("action", "reason"), [("suspend", "x"), ("stop", None), ("retire", None)])
    def test_repeated_operator_action_is_409_and_writes_nothing(self, gw, api, action, reason):
        body = {"action": action} | ({"reason": reason} if reason else {})
        assert api.post("/api/v1/gateways/g1/actions", body, format="json").status_code == 200
        before = snapshot()
        assert api.post("/api/v1/gateways/g1/actions", body, format="json").status_code == 409
        assert snapshot() == before


@pytest.mark.django_db
class TestTwoWorkersOnTheSameDueWork:
    """Two workers can pick the same due item; the second run must find it no longer due."""

    def test_a_batch_attempt_runs_once(self, api, clock_at):
        gw = device(setup_world(api, clock_at))
        api.post("/test/faults", {"processing_failures": 1}, format="json")
        gw.put("/gw/v1/batches/b1", BATCH, format="json")
        processing.attempt("b1", at(1, 12))  # fails: retry due at 12:01
        processing.attempt("b1", at(1, 12))  # a second worker that picked the same item
        batch = Batch.objects.get()
        assert (batch.processing, batch.attempts, batch.next_attempt_at) == ("retrying", 1, at(1, 12, 1))

    def test_a_processed_batch_is_not_processed_again(self, api, clock_at):
        gw = device(setup_world(api, clock_at))
        gw.put("/gw/v1/batches/b1", BATCH, format="json")
        processing.attempt("b1", at(1, 12))
        before = snapshot()
        processing.attempt("b1", at(1, 12))
        assert (Batch.objects.get().attempts, snapshot()) == (1, before)

    def test_a_command_timeout_after_the_ack_changes_nothing(self, api, clock_at):
        gw = device(setup_world(api, clock_at))
        api.post("/api/v1/gateways/g1/actions", {"action": "stop"}, format="json")
        [command] = gw.get("/gw/v1/commands").json()["commands"]
        gw.post(f"/gw/v1/commands/{command['command_id']}/ack", {"acked_at": iso(1, 12)}, format="json")
        before = snapshot()
        commands.run_timeout(command["command_id"], at(1, 12, 10))
        assert snapshot() == before
        assert Command.objects.get().timed_out is False
        assert timeline.entries("gateway", "g1").last().rule == "ack_stop"


def concurrently(n, fn):
    """Run fn(i) in n threads at once; each thread uses (and closes) its own database connection."""

    def run(i):
        try:
            return fn(i)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


@pytest.mark.django_db(transaction=True)
class TestConcurrentDuplicates:
    """Identical requests arriving at the same time produce one effect: one 202, the rest 200."""

    N = 6

    @pytest.fixture
    def token(self, api, test_mode):
        api.post("/test/clock", {"now": iso(1, 12)}, format="json")
        token = register_gateway(api)
        register_sensor(api, "s1")
        set_coverage(api, "s1", ["g1"])
        return token

    def test_cycles(self, token):
        statuses = concurrently(self.N, lambda i: device(token).post("/gw/v1/cycles", CYCLE, format="json").status_code)
        assert sorted(statuses) == [200] * (self.N - 1) + [202]
        assert (Cycle.objects.count(), CycleResult.objects.count()) == (1, 1)

    def test_batches(self, token):
        statuses = concurrently(
            self.N, lambda i: device(token).put("/gw/v1/batches/b1", BATCH, format="json").status_code
        )
        assert sorted(statuses) == [200] * (self.N - 1) + [202]
        assert Batch.objects.count() == 1
        assert len([e for e in timeline.entries("batch", "b1") if e.to_value == "received"]) == 1

    def test_acks(self, token, api):
        api.post("/api/v1/gateways/g1/actions", {"action": "stop"}, format="json")
        [command] = device(token).get("/gw/v1/commands").json()["commands"]
        path = f"/gw/v1/commands/{command['command_id']}/ack"
        statuses = concurrently(
            self.N, lambda i: device(token).post(path, {"acked_at": iso(1, 12)}, format="json").status_code
        )
        assert statuses == [204] * self.N
        assert len([e for e in timeline.entries("gateway", "g1") if e.kind == "ack"]) == 1

    def test_two_ticks_process_a_batch_once(self, token, api):
        from core.tick import tick

        device(token).put("/gw/v1/batches/b1", BATCH, format="json")
        concurrently(2, lambda i: tick(at(1, 12)))
        batch = Batch.objects.get()
        assert (batch.processing, batch.attempts, Reading.objects.count()) == ("processed", 1, 1)
