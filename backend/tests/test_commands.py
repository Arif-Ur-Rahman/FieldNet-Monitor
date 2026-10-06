"""Stop and resume: one test class per row of the brief's table, plus acks, timeouts and the flag."""

import pytest

from core import timeline
from gateways.models import Command
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


class Steps:
    def __init__(self, api, client):
        self.api, self.client, self.n = api, client, 0

    def clock(self, day, hour=0, minute=0):
        assert self.api.post("/test/clock", {"now": iso(day, hour, minute)}, format="json").status_code == 200

    def action(self, action, expect=200):
        resp = self.api.post("/api/v1/gateways/g1/actions", {"action": action}, format="json")
        assert resp.status_code == expect, resp.content
        return resp.json()

    def commands(self, client=None):
        resp = (client or self.client).get("/gw/v1/commands")
        assert resp.status_code == 200, resp.content
        return resp.json()["commands"]

    def latest_id(self):
        return Command.objects.order_by("-seq").first().command_id

    def ack(self, command_id=None, acked=(1, 0, 1), expect=204, client=None):
        resp = (client or self.client).post(
            f"/gw/v1/commands/{command_id or self.latest_id()}/ack", {"acked_at": iso(*acked)}, format="json"
        )
        assert resp.status_code == expect, resp.content
        return resp

    def batch(self, *taken):
        self.n += 1
        readings = [
            {"reading_id": f"r{self.n}-{i}", "taken_at": iso(*t), "value": 1.0, "unit": "C"}
            for i, t in enumerate(taken)
        ]
        resp = self.client.put(f"/gw/v1/batches/b{self.n}", {"sensor_id": "s1", "readings": readings}, format="json")
        assert resp.status_code == 202, resp.content
        assert self.api.post("/test/drain").status_code == 200
        return self.api.get(f"/api/v1/batches/b{self.n}").json()

    def gateway(self):
        return self.api.get("/api/v1/gateways/g1").json()

    def state(self):
        return self.gateway()["command_state"]

    def sensor_coverage(self):
        return self.api.get("/api/v1/sensors/s1").json()["coverage"]

    def entries(self, kind=None, axis=None):
        return [
            e
            for e in timeline.entries("gateway", "g1")
            if (kind is None or e.kind == kind) and (axis is None or e.axis == axis)
        ]

    def transitions(self):
        return [(e.from_value, e.to_value, e.effective_at, e.rule) for e in self.entries("transition", "command_state")]


@pytest.fixture
def go(api, clock_at):
    """Gateway g1, connected and running, covering s1. Clock at day 1 00:00."""
    clock_at(1)
    token = register_gateway(api)
    register_sensor(api, "s1")
    set_coverage(api, "s1", ["g1"])
    client = device(token)
    body = {
        "cycle_id": "c0",
        "started_at": iso(1),
        "finished_at": iso(1),
        "session": "ok",
        "results": [{"sensor_id": "s1", "outcome": "no_readings"}],
    }
    assert client.post("/gw/v1/cycles", body, format="json").status_code == 202
    steps = Steps(api, client)
    assert (steps.gateway()["status"], steps.state()) == ("connected", "running")
    return steps


def stopped(go):
    go.action("stop")
    go.ack(acked=(1, 0, 1))
    assert go.state() == "stopped"


class TestRunningToStopPending:
    def test_operator_stop(self, go):
        g = go.action("stop")
        assert (g["command_state"], g["coverage_class"]) == ("stop_pending", "available")
        assert go.transitions() == [("running", "stop_pending", at(1), "stop")]
        [command] = go.commands()
        assert set(command) == {"command_id", "seq", "type", "issued_at"}
        assert (command["seq"], command["type"], command["issued_at"]) == (1, "stop", iso(1))

    def test_writes_an_action_entry(self, go):
        go.action("stop")
        assert [e.rule for e in go.entries("action")] == ["stop"]


class TestStopPendingToStopped:
    def test_ack_stops_it_at_acked_at(self, go):
        go.action("stop")
        go.clock(1, 0, 2)
        go.ack(acked=(1, 0, 1))
        g = go.gateway()
        assert (g["command_state"], g["coverage_class"]) == ("stopped", "stopped")
        assert go.transitions()[-1] == ("stop_pending", "stopped", at(1, 0, 1), "ack_stop")
        assert go.sensor_coverage() == "stopped"
        assert go.commands() == []


class TestStopPendingToStopFailed:
    def test_no_ack_within_10_minutes(self, go):
        go.action("stop")
        go.clock(1, 0, 9)
        assert go.state() == "stop_pending"
        go.clock(1, 3)
        g = go.gateway()
        # Effective at the timeout, not the clock jump; still available (no proof it stopped).
        assert (g["command_state"], g["coverage_class"]) == ("stop_failed", "available")
        assert go.transitions()[-1] == ("stop_pending", "stop_failed", at(1, 0, 10), "command_timeout")

    def test_failed_command_is_still_served_until_acknowledged(self, go):
        go.action("stop")
        go.clock(2)
        assert [c["type"] for c in go.commands()] == ["stop"]


class TestStopFailedToStopped:
    def test_late_ack_of_the_latest_stop(self, go):
        go.action("stop")
        go.clock(1, 1)
        go.ack(acked=(1, 0, 30))
        assert go.state() == "stopped"
        # Not effective before the failure it follows.
        assert go.transitions()[-1] == ("stop_failed", "stopped", at(1, 0, 30), "ack_stop")


class TestToResumePending:
    @pytest.mark.parametrize("start", ["stop_pending", "stopped", "stop_failed"])
    def test_operator_resume_supersedes_the_stop(self, go, start):
        go.action("stop")
        if start == "stopped":
            go.ack()
        if start == "stop_failed":
            go.clock(1, 0, 10)
        assert go.state() == start
        go.clock(1, 0, 20)
        g = go.action("resume")
        assert g["command_state"] == "resume_pending"
        [command] = go.commands()
        assert (command["seq"], command["type"]) == (2, "resume")
        assert Command.objects.get(seq=1).superseded


class TestResumePendingToRunning:
    def test_ack_resumes(self, go):
        stopped(go)
        go.clock(1, 1)
        go.action("resume")
        go.ack(acked=(1, 1, 1))
        g = go.gateway()
        assert (g["command_state"], g["coverage_class"]) == ("running", "available")
        assert go.sensor_coverage() == "available"
        assert go.transitions()[-1] == ("resume_pending", "running", at(1, 1, 1), "ack_resume")


class TestResumePendingToResumeFailed:
    def test_no_ack_within_10_minutes(self, go):
        stopped(go)
        go.clock(1, 1)
        go.action("resume")
        go.clock(1, 2)
        g = go.gateway()
        # No proof it resumed: still stopped.
        assert (g["command_state"], g["coverage_class"]) == ("resume_failed", "stopped")
        assert go.transitions()[-1] == ("resume_pending", "resume_failed", at(1, 1, 10), "command_timeout")


class TestResumeFailedToRunning:
    def test_late_ack_of_the_latest_resume(self, go):
        stopped(go)
        go.clock(1, 1)
        go.action("resume")
        go.clock(1, 2)
        go.ack(acked=(1, 1, 30))
        assert go.state() == "running"


class TestResumeToStopPending:
    @pytest.mark.parametrize("start", ["resume_pending", "resume_failed"])
    def test_operator_stop_supersedes_the_resume(self, go, start):
        stopped(go)
        go.clock(1, 1)
        go.action("resume")
        if start == "resume_failed":
            go.clock(1, 2)
        assert go.state() == start
        assert go.action("stop")["command_state"] == "stop_pending"
        assert [c["seq"] for c in go.commands()] == [3]


class TestIllegal:
    @pytest.mark.parametrize("start", ["stop_pending", "stopped"])
    def test_stop_while_stop_pending_or_stopped_is_409(self, go, start):
        go.action("stop")
        if start == "stopped":
            go.ack()
        assert go.action("stop", expect=409)["error"] == "illegal_command"

    def test_resume_while_running_is_409(self, go):
        assert go.action("resume", expect=409)["error"] == "illegal_command"

    def test_resume_while_resume_pending_is_409(self, go):
        stopped(go)
        go.action("resume")
        assert go.action("resume", expect=409)["error"] == "illegal_command"

    def test_stop_again_after_stop_failed_issues_a_new_stop(self, go):
        go.action("stop")
        go.clock(1, 0, 10)
        assert go.action("stop")["command_state"] == "stop_pending"
        assert [c["seq"] for c in go.commands()] == [2]

    def test_resume_again_after_resume_failed_issues_a_new_resume(self, go):
        stopped(go)
        go.clock(1, 1)
        go.action("resume")
        go.clock(1, 2)
        assert go.action("resume")["command_state"] == "resume_pending"

    def test_retired_gateway_is_409(self, go):
        go.action("retire")
        assert go.action("stop", expect=409)["error"] == "gateway_retired"


class TestAcks:
    def test_repeat_is_204_and_changes_nothing(self, go):
        go.action("stop")
        go.ack(acked=(1, 0, 1))
        go.ack(acked=(1, 0, 1))
        go.ack(acked=(1, 0, 2))
        assert len(go.entries("ack")) == 1
        assert Command.objects.get().acked_at == at(1, 0, 1)

    def test_unknown_command_is_404(self, go):
        assert go.ack("nope", expect=404).json()["error"] == "command_not_found"

    def test_another_gateways_command_is_404(self, go, api):
        go.action("stop")
        other = device(register_gateway(api, "g2", "Gateway 2"))
        go.ack(go.latest_id(), client=other, expect=404)
        assert go.state() == "stop_pending"

    def test_ack_of_a_superseded_command_is_recorded_only(self, go):
        go.action("stop")
        stop_id = go.latest_id()
        go.action("resume")
        go.ack(stop_id, acked=(1, 0, 1))
        assert go.state() == "resume_pending"
        [ack] = go.entries("ack")
        assert (ack.rule, ack.detail["superseded"], ack.evidence_ids) == ("ack_stop", True, [f"command-{stop_id}"])

    def test_acked_at_more_than_5_minutes_ahead_is_422(self, go):
        go.action("stop")
        assert go.ack(acked=(1, 0, 6), expect=422).json()["error"] == "timestamp_in_future"

    def test_unknown_token_is_401(self, go):
        go.action("stop")
        go.ack(client=device("nope"), expect=401)

    def test_acknowledged_command_never_times_out(self, go):
        go.action("stop")
        go.ack()
        go.clock(2)
        assert go.state() == "stopped"

    def test_superseded_command_never_times_out(self, go):
        go.action("stop")
        go.clock(1, 0, 5)
        go.action("resume")
        go.clock(1, 0, 12)
        # Only the resume (issued 00:05) can fail, at 00:15.
        assert go.state() == "resume_pending"
        go.clock(1, 0, 15)
        assert go.state() == "resume_failed"


class TestCollectingAfterStop:
    def test_reading_inside_the_stop_period_raises_the_flag(self, go):
        stopped(go)
        go.clock(1, 2)
        b = go.batch((1, 1))
        # Kept and counted.
        assert (b["processing"], b["accepted_count"]) == ("processed", 1)
        assert go.gateway()["flags"] == ["collecting_after_stop"]
        [flag] = go.entries("flag")
        assert (flag.from_value, flag.to_value, flag.effective_at) == (None, "collecting_after_stop", at(1, 1))

    def test_reading_before_the_stop_ack_does_not(self, go):
        stopped(go)
        go.clock(1, 2)
        go.batch((1, 0, 0))
        assert go.gateway()["flags"] == []
        assert go.entries("flag") == []

    def test_unacknowledged_stop_has_no_stop_period(self, go):
        go.action("stop")
        go.clock(1, 2)
        go.batch((1, 1))
        assert go.gateway()["flags"] == []

    def test_resume_ack_clears_it(self, go):
        stopped(go)
        go.clock(1, 2)
        go.batch((1, 1))
        go.action("resume")
        go.ack(acked=(1, 2, 1))
        assert go.gateway()["flags"] == []
        assert [(e.from_value, e.to_value, e.rule) for e in go.entries("flag")][-1] == (
            "collecting_after_stop",
            None,
            "resume_acked",
        )

    def test_reading_after_the_resume_ack_does_not_raise_it(self, go):
        stopped(go)
        go.clock(1, 2)
        go.action("resume")
        go.ack(acked=(1, 2))
        go.clock(1, 4)
        go.batch((1, 3))
        assert go.gateway()["flags"] == []

    def test_late_reading_in_a_past_period_is_recorded_but_does_not_raise_it(self, go):
        stopped(go)
        go.clock(1, 2)
        go.action("resume")
        go.ack(acked=(1, 2))
        go.clock(1, 4)
        go.batch((1, 1))
        assert go.gateway()["flags"] == []
        [flag] = go.entries("flag")
        assert (flag.effective_at, flag.detail["period_open"]) == (at(1, 1), False)

    def test_late_stop_ack_flags_readings_already_accepted(self, go):
        go.action("stop")
        go.clock(1, 2)
        go.batch((1, 1))
        assert go.gateway()["flags"] == []
        go.ack(acked=(1, 0, 30))
        assert go.gateway()["flags"] == ["collecting_after_stop"]

    def test_resume_issued_but_not_acked_keeps_the_period_open(self, go):
        stopped(go)
        go.clock(1, 1)
        go.action("resume")
        go.clock(1, 2)
        go.batch((1, 1, 30))
        assert go.gateway()["flags"] == ["collecting_after_stop"]
