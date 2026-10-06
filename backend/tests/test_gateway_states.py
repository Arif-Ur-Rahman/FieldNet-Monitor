"""One test class per row of the brief's gateway transition table, plus timing and coverage."""

import pytest

from core import timeline
from gateways.models import Gateway
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


@pytest.fixture
def g1(api, clock_at):
    """Gateway g1 covering sensor s1, both new. Clock at day 1 00:00."""
    clock_at(1)
    token = register_gateway(api)
    register_sensor(api, "s1")
    set_coverage(api, "s1", ["g1"])
    return device(token)


class Steps:
    """Drive the gateway API and the test clock."""

    def __init__(self, api, client):
        self.api, self.client, self.n = api, client, 0

    def clock(self, day, hour=0, minute=0):
        resp = self.api.post("/test/clock", {"now": iso(day, hour, minute)}, format="json")
        assert resp.status_code == 200, resp.content

    def cycle(self, finished, session="ok", outcome="no_readings", sensor="s1"):
        self.n += 1
        result = {"sensor_id": sensor, "outcome": outcome}
        if outcome == "readings":
            result["batch_id"] = f"b{self.n}"
        body = {
            "cycle_id": f"c{self.n}",
            "started_at": iso(*finished),
            "finished_at": iso(*finished),
            "session": session,
            "results": [result],
        }
        resp = self.client.post("/gw/v1/cycles", body, format="json")
        assert resp.status_code == 202, resp.content

    def heartbeat(self, sent, session="ok"):
        resp = self.client.post("/gw/v1/heartbeat", {"sent_at": iso(*sent), "session": session}, format="json")
        assert resp.status_code == 204, resp.content

    def batch(self, taken, batch_id=None):
        self.n += 1
        body = {
            "sensor_id": "s1",
            "readings": [{"reading_id": f"r{self.n}", "taken_at": iso(*taken), "value": 1.0, "unit": "C"}],
        }
        resp = self.client.put(f"/gw/v1/batches/{batch_id or f'b{self.n}'}", body, format="json")
        assert resp.status_code == 202, resp.content
        assert self.api.post("/test/drain").status_code == 200

    def action(self, action, reason=None, expect=200, gateway="g1"):
        body = {"action": action} | ({"reason": reason} if reason is not None else {})
        resp = self.api.post(f"/api/v1/gateways/{gateway}/actions", body, format="json")
        assert resp.status_code == expect, resp.content
        return resp.json()

    def gateway(self, gateway="g1"):
        return self.api.get(f"/api/v1/gateways/{gateway}").json()

    def status(self):
        return self.gateway()["status"]

    def sensor_coverage(self, sensor="s1"):
        return self.api.get(f"/api/v1/sensors/{sensor}").json()["coverage"]

    def transitions(self, axis="status", entity=("gateway", "g1")):
        return [
            (e.from_value, e.to_value, e.effective_at, e.rule)
            for e in timeline.entries(*entity)
            if e.kind == "transition" and e.axis == axis
        ]


@pytest.fixture
def go(api, g1):
    return Steps(api, g1)


def connect(go, day=1, hour=0):
    go.clock(day, hour)
    go.cycle((day, hour))
    assert go.status() == "connected"


class TestNewToConnected:
    def test_qualifying_cycle_connects_at_its_finished_at(self, go):
        go.clock(1, 12)
        go.cycle((1, 11, 55))
        g = go.gateway()
        assert g["status"] == "connected"
        assert g["status_since"] == g["last_qualifying_at"] == iso(1, 11, 55)
        assert g["coverage_class"] == "available"
        assert go.transitions() == [("new", "connected", at(1, 11, 55), "qualifying_evidence")]

    def test_readings_outcome_qualifies_too(self, go):
        go.clock(1, 12)
        go.cycle((1, 12), outcome="readings")
        assert go.status() == "connected"

    def test_processed_batch_qualifies_at_its_latest_accepted_taken_at(self, go):
        go.clock(1, 12)
        go.batch((1, 10))
        g = go.gateway()
        assert (g["status"], g["last_qualifying_at"]) == ("connected", iso(1, 10))

    @pytest.mark.parametrize("outcome", ["could_not_read", "timeout"])
    def test_cycle_without_readings_or_no_readings_does_not_qualify(self, go, outcome):
        go.clock(1, 12)
        go.cycle((1, 12), outcome=outcome)
        assert go.status() == "new"

    def test_heartbeats_never_qualify(self, go):
        go.clock(1, 12)
        go.heartbeat((1, 12))
        g = go.gateway()
        assert (g["status"], g["last_heartbeat_at"], g["last_qualifying_at"]) == ("new", iso(1, 12), None)

    def test_ignored_results_do_not_qualify(self, go, api):
        register_sensor(api, "s9")
        go.clock(1, 12)
        go.cycle((1, 12), sensor="s9")
        assert go.status() == "new"

    def test_quarantined_batch_does_not_qualify(self, go):
        go.clock(1, 12)
        resp = go.client.put("/gw/v1/batches/bad", {"sensor_id": "s1", "readings": [{"x": 1}]}, format="json")
        assert resp.status_code == 202
        go.api.post("/test/drain")
        assert go.status() == "new"

    def test_coverage_of_covered_sensors_follows(self, go):
        assert go.sensor_coverage() == "recoverable"
        go.clock(1, 12)
        go.cycle((1, 11))
        assert go.sensor_coverage() == "available"
        # Coverage changes are timed by the server clock.
        assert go.transitions("coverage", ("sensor", "s1"))[-1][1:3] == ("available", at(1, 12))

    def test_a_new_gateway_without_evidence_stays_new(self, go):
        go.clock(400)
        assert go.status() == "new"


class TestNewToSpare:
    def test_mark_spare_when_it_covers_no_sensors(self, go, api):
        set_coverage(api, "s1", [])
        g = go.action("mark_spare")
        assert (g["status"], g["coverage_class"]) == ("spare", "recoverable")

    def test_409_while_it_covers_sensors(self, go):
        assert go.action("mark_spare", expect=409)["error"] == "gateway_covers_sensors"

    def test_409_unless_new(self, go, api):
        connect(go)
        set_coverage(api, "s1", [])
        assert go.action("mark_spare", expect=409)["error"] == "illegal_transition"


class TestSpareToNew:
    def test_assigning_a_sensor_makes_it_new(self, go, api):
        set_coverage(api, "s1", [])
        go.action("mark_spare")
        set_coverage(api, "s1", ["g1"])
        assert go.status() == "new"


class TestConnectedToStale:
    def test_twelve_hours_after_last_qualifying_at(self, go):
        connect(go, 1, 6)
        go.clock(1, 17, 59)
        assert go.status() == "connected"
        go.clock(3)
        g = go.gateway()
        # Effective at its own due time, not the clock jump.
        assert (g["status"], g["status_since"], g["coverage_class"]) == ("stale", iso(1, 18), "recoverable")
        assert go.transitions()[-1] == ("connected", "stale", at(1, 18), "no_qualifying_evidence")
        assert go.sensor_coverage() == "recoverable"

    def test_newer_evidence_moves_the_deadline(self, go):
        connect(go, 1, 6)
        go.clock(1, 12)
        go.cycle((1, 12))
        go.clock(1, 23)
        assert go.status() == "connected"
        go.clock(2, 0)
        assert go.gateway()["status_since"] == iso(2, 0)

    def test_heartbeats_do_not_keep_it_connected(self, go):
        connect(go, 1, 6)
        go.clock(1, 12)
        go.heartbeat((1, 12))
        go.clock(1, 18)
        assert go.status() == "stale"

    def test_evidence_already_too_old_connects_then_goes_stale_at_once(self, go):
        go.clock(2, 13)
        go.cycle((2, 0))
        # The first evidence arrives 13h late: new → connected at its event time, then stale at once.
        assert go.status() == "stale"
        assert go.transitions() == [
            ("new", "connected", at(2, 0), "qualifying_evidence"),
            ("connected", "stale", at(2, 12), "no_qualifying_evidence"),
        ]

    def test_late_batch_processed_at_a_jump_keeps_it_connected(self, go):
        # The batch is due (11:00) before the stale deadline (12:00), so the jump processes it first.
        connect(go, 1, 0)
        go.clock(1, 11)
        go.client.put(
            "/gw/v1/batches/late",
            {"sensor_id": "s1", "readings": [{"reading_id": "x", "taken_at": iso(1, 11), "value": 1, "unit": "C"}]},
            format="json",
        )
        go.clock(1, 13)
        assert go.status() == "connected"


class TestStaleToConnected:
    def test_evidence_from_the_last_12_hours_reconnects(self, go):
        connect(go, 1, 0)
        go.clock(2)
        assert go.status() == "stale"
        go.cycle((1, 23))
        g = go.gateway()
        assert (g["status"], g["status_since"], g["coverage_class"]) == ("connected", iso(1, 23), "available")
        assert go.sensor_coverage() == "available"

    def test_older_late_evidence_changes_no_status(self, go):
        connect(go, 1, 0)
        go.clock(2)
        go.cycle((1, 11))
        g = go.gateway()
        # 13h old: no reconnection, but last_qualifying_at only ever moves forward.
        assert (g["status"], g["last_qualifying_at"]) == ("stale", iso(1, 11))

    def test_late_evidence_older_than_last_qualifying_at_changes_nothing(self, go):
        connect(go, 1, 6)
        go.cycle((1, 5))
        assert go.gateway()["last_qualifying_at"] == iso(1, 6)


class TestToDisconnected:
    @pytest.mark.parametrize("start", ["new", "connected", "stale"])
    def test_auth_failed_heartbeat_disconnects(self, go, start):
        if start == "connected":
            connect(go, 2, 0)
        if start == "stale":
            connect(go, 1, 0)
            go.clock(2)
        go.clock(2, 6)
        assert go.status() == start
        go.heartbeat((2, 5), session="auth_failed")
        g = go.gateway()
        assert (g["status"], g["disconnected_since"], g["status_since"]) == ("disconnected", iso(2, 5), iso(2, 5))
        assert g["coverage_class"] == "recoverable"
        assert go.transitions()[-1] == (start, "disconnected", at(2, 5), "auth_failed")

    def test_auth_failed_cycle_disconnects_at_its_finished_at(self, go):
        connect(go, 1, 0)
        go.clock(1, 6)
        go.cycle((1, 5), session="auth_failed")
        g = go.gateway()
        assert (g["status"], g["disconnected_since"]) == ("disconnected", iso(1, 5))
        assert go.sensor_coverage() == "recoverable"

    def test_later_failures_keep_the_first_time(self, go):
        go.clock(1, 6)
        go.heartbeat((1, 5), session="auth_failed")
        go.clock(1, 8)
        go.heartbeat((1, 7), session="auth_failed")
        go.cycle((1, 8), session="auth_failed")
        assert go.gateway()["disconnected_since"] == iso(1, 5)
        assert len(go.transitions()) == 1

    def test_failure_older_than_last_qualifying_does_not_disconnect(self, go):
        connect(go, 1, 6)
        go.heartbeat((1, 5), session="auth_failed")
        assert go.status() == "connected"


class TestDisconnectedToConnected:
    @pytest.fixture
    def disconnected(self, go):
        connect(go, 1, 0)
        go.clock(1, 6)
        go.heartbeat((1, 5), session="auth_failed")
        assert go.status() == "disconnected"
        return go

    def test_qualifying_evidence_after_disconnected_since_reconnects(self, disconnected):
        go = disconnected
        go.clock(1, 8)
        go.cycle((1, 7))
        g = go.gateway()
        assert (g["status"], g["status_since"], g["disconnected_since"]) == ("connected", iso(1, 7), None)
        assert go.transitions()[-1] == ("disconnected", "connected", at(1, 7), "qualifying_evidence")

    def test_ok_heartbeat_is_not_enough(self, disconnected):
        disconnected.clock(1, 8)
        disconnected.heartbeat((1, 7))
        assert disconnected.status() == "disconnected"

    def test_old_batch_resent_after_the_failure_is_not_enough(self, disconnected):
        disconnected.clock(1, 8)
        disconnected.batch((1, 4))
        g = disconnected.gateway()
        assert (g["status"], g["last_qualifying_at"]) == ("disconnected", iso(1, 4))

    def test_evidence_from_before_the_failure_is_not_enough(self, disconnected):
        disconnected.clock(1, 8)
        disconnected.cycle((1, 4))
        assert disconnected.status() == "disconnected"


class TestSuspend:
    @pytest.mark.parametrize("start", ["new", "connected", "disconnected"])
    def test_suspend_from_any_status_but_retired(self, go, start):
        if start == "connected":
            connect(go)
        if start == "disconnected":
            go.clock(1, 1)
            go.heartbeat((1, 1), session="auth_failed")
        g = go.action("suspend", "maintenance")
        assert (g["status"], g["coverage_class"], g["disconnected_since"]) == ("suspended", "dead", None)
        assert go.sensor_coverage() == "none"
        action = [e for e in timeline.entries("gateway", "g1") if e.kind == "action"][-1]
        assert (action.rule, action.detail) == ("suspend", {"reason": "maintenance"})

    @pytest.mark.parametrize("reason", [None, "", "   "])
    def test_reason_is_required(self, go, reason):
        assert go.action("suspend", reason, expect=422)["error"] == "invalid_body"

    def test_twice_is_409(self, go):
        go.action("suspend", "x")
        assert go.action("suspend", "x", expect=409)["error"] == "already_suspended"

    def test_automatic_rules_do_not_change_it_but_timestamps_keep_updating(self, go):
        go.action("suspend", "x")
        go.clock(1, 12)
        go.cycle((1, 11))
        go.heartbeat((1, 12))
        go.heartbeat((1, 12), session="auth_failed")
        go.clock(5)
        g = go.gateway()
        assert (g["status"], g["last_qualifying_at"], g["last_heartbeat_at"]) == ("suspended", iso(1, 11), iso(1, 12))
        assert Gateway.objects.get().last_auth_failure_at == at(1, 12)


class TestUnsuspend:
    def test_new_when_there_was_never_qualifying_evidence(self, go):
        go.action("suspend", "x")
        assert go.action("unsuspend")["status"] == "new"

    def test_connected_when_last_qualifying_is_within_12_hours(self, go):
        go.action("suspend", "x")
        go.clock(1, 12)
        go.cycle((1, 11))
        go.clock(1, 20)
        g = go.action("unsuspend")
        assert (g["status"], g["status_since"], g["coverage_class"]) == ("connected", iso(1, 20), "available")
        assert go.sensor_coverage() == "available"

    def test_stale_when_last_qualifying_is_older(self, go):
        go.action("suspend", "x")
        go.clock(1, 12)
        go.cycle((1, 11))
        go.clock(2)
        assert go.action("unsuspend")["status"] == "stale"

    def test_disconnected_when_the_latest_auth_failure_is_newer(self, go):
        connect(go, 1, 0)
        go.action("suspend", "x")
        go.clock(1, 6)
        go.heartbeat((1, 2), session="auth_failed")
        go.heartbeat((1, 5), session="auth_failed")
        g = go.action("unsuspend")
        assert (g["status"], g["disconnected_since"]) == ("disconnected", iso(1, 2))

    def test_unsuspended_gateway_follows_the_rules_again(self, go):
        go.action("suspend", "x")
        go.clock(1, 12)
        go.cycle((1, 11))
        go.action("unsuspend")
        go.clock(2)
        assert go.status() == "stale"

    def test_409_unless_suspended(self, go):
        assert go.action("unsuspend", expect=409)["error"] == "not_suspended"


class TestRetire:
    @pytest.mark.parametrize("start", ["new", "connected", "suspended"])
    def test_retire_from_any_status(self, go, start):
        if start == "connected":
            connect(go)
        if start == "suspended":
            go.action("suspend", "x")
        g = go.action("retire", "end of life")
        assert (g["status"], g["coverage_class"]) == ("retired", "dead")
        assert go.sensor_coverage() == "none"

    def test_terminal(self, go):
        go.action("retire")
        for action, reason in [("retire", None), ("suspend", "x"), ("unsuspend", None)]:
            assert go.action(action, reason, expect=409)["error"] == "gateway_retired"

    def test_later_gateway_requests_are_403_and_change_nothing(self, go):
        go.action("retire")
        go.clock(1, 1)
        body = {"sent_at": iso(1, 1), "session": "ok"}
        assert go.client.post("/gw/v1/heartbeat", body, format="json").status_code == 403
        assert go.gateway()["last_heartbeat_at"] is None


class TestActionsEndpoint:
    def test_unknown_gateway_is_404(self, go):
        assert go.action("retire", gateway="nope", expect=404)["error"] == "gateway_not_found"

    @pytest.mark.parametrize("body", [{}, {"action": "explode"}, {"action": "stop_everything"}])
    def test_invalid_body_is_422(self, go, body):
        assert go.api.post("/api/v1/gateways/g1/actions", body, format="json").status_code == 422

    def test_returns_the_gateway_state_shape(self, go):
        g = go.action("suspend", "x")
        assert set(g) == {
            "gateway_id",
            "name",
            "status",
            "status_since",
            "command_state",
            "coverage_class",
            "last_heartbeat_at",
            "last_qualifying_at",
            "disconnected_since",
            "flags",
        }
