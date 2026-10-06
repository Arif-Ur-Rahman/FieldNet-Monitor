import pytest

from gateways.models import Cycle, CycleResult, Gateway, Heartbeat
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


@pytest.fixture
def gw(api, clock_at):
    """Gateway g1 covering s1 and s2; s3 exists but is not covered. Clock at day 1 12:00."""
    clock_at(1, 12)
    token = register_gateway(api)
    for sid in ("s1", "s2", "s3"):
        register_sensor(api, sid)
    set_coverage(api, "s1", ["g1"])
    set_coverage(api, "s2", ["g1"])
    return device(token)


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


def cycle(cycle_id="c1", session="ok", results=None, finished=(1, 11, 55)):
    return {
        "cycle_id": cycle_id,
        "started_at": iso(1, 11, 50),
        "finished_at": iso(*finished),
        "session": session,
        "results": results
        if results is not None
        else [
            {"sensor_id": "s1", "outcome": "readings", "batch_id": "b1"},
            {"sensor_id": "s2", "outcome": "no_readings"},
        ],
    }


class TestAuth:
    def test_unknown_token_is_401(self, gw):
        assert device("nope").post("/gw/v1/heartbeat", {}, format="json").status_code == 401

    def test_retired_gateway_is_403_and_changes_nothing(self, gw):
        Gateway.objects.filter(pk="g1").update(status="retired")
        resp = gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 12), "session": "ok"}, format="json")
        assert resp.status_code == 403
        assert not Heartbeat.objects.exists()
        assert gw.post("/gw/v1/cycles", cycle(), format="json").status_code == 403
        assert not Cycle.objects.exists()


class TestHeartbeat:
    def test_records_and_sets_last_heartbeat_at_to_received_time(self, gw, api):
        resp = gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 11, 59), "session": "ok"}, format="json")
        assert resp.status_code == 204
        assert api.get("/api/v1/gateways/g1").json()["last_heartbeat_at"] == iso(1, 12)

    def test_auth_failed_heartbeat_is_recorded(self, gw):
        assert (
            gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 12), "session": "auth_failed"}, format="json").status_code
            == 204
        )
        assert Heartbeat.objects.get().session == "auth_failed"

    def test_repeat_is_safe(self, gw):
        body = {"sent_at": iso(1, 12), "session": "ok"}
        assert gw.post("/gw/v1/heartbeat", body, format="json").status_code == 204
        assert gw.post("/gw/v1/heartbeat", body, format="json").status_code == 204
        assert Heartbeat.objects.count() == 1

    def test_late_heartbeat_does_not_move_last_heartbeat_at_back(self, gw, api, clock_at):
        gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 12), "session": "ok"}, format="json")
        clock_at(1, 13)
        gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 13), "session": "ok"}, format="json")
        assert api.get("/api/v1/gateways/g1").json()["last_heartbeat_at"] == iso(1, 13)

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"sent_at": "yesterday", "session": "ok"},
            {"sent_at": iso(1, 12)},
            {"sent_at": iso(1, 12), "session": "meh"},
        ],
    )
    def test_invalid_body_is_422(self, gw, body):
        assert gw.post("/gw/v1/heartbeat", body, format="json").status_code == 422

    def test_more_than_5_minutes_ahead_is_422(self, gw):
        assert (
            gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 12, 5), "session": "ok"}, format="json").status_code == 204
        )
        resp = gw.post("/gw/v1/heartbeat", {"sent_at": iso(1, 12, 6), "session": "ok"}, format="json")
        assert resp.status_code == 422
        assert resp.json()["error"] == "timestamp_in_future"


class TestCycle:
    def test_records_results_and_lists_ignored(self, gw):
        body = cycle(
            results=[
                {"sensor_id": "s1", "outcome": "readings", "batch_id": "b1"},
                {"sensor_id": "s2", "outcome": "timeout"},
                {"sensor_id": "s3", "outcome": "no_readings"},
                {"sensor_id": "ghost", "outcome": "could_not_read"},
            ]
        )
        resp = gw.post("/gw/v1/cycles", body, format="json")
        assert resp.status_code == 202
        assert resp.json() == {"ignored": ["s3", "ghost"]}
        results = {r.sensor_id: (r.outcome, r.batch_id) for r in CycleResult.objects.all()}
        assert results == {"s1": ("readings", "b1"), "s2": ("timed_out", None)}
        assert CycleResult.objects.get(sensor_id="s1").finished_at == at(1, 11, 55)

    def test_identical_repeat_is_200_and_changes_nothing(self, gw):
        assert gw.post("/gw/v1/cycles", cycle(), format="json").status_code == 202
        resp = gw.post("/gw/v1/cycles", cycle(), format="json")
        assert resp.status_code == 200
        assert resp.json() == {"ignored": []}
        assert (Cycle.objects.count(), CycleResult.objects.count()) == (1, 2)

    def test_same_id_different_body_is_409(self, gw):
        gw.post("/gw/v1/cycles", cycle(), format="json")
        resp = gw.post("/gw/v1/cycles", cycle(session="auth_failed"), format="json")
        assert resp.status_code == 409
        assert resp.json()["error"] == "cycle_conflict"

    def test_auth_failed_records_every_outcome_as_could_not_read(self, gw):
        gw.post("/gw/v1/cycles", cycle(session="auth_failed"), format="json")
        assert {(r.outcome, r.reported_outcome, r.batch_id) for r in CycleResult.objects.all()} == {
            ("could_not_read", "readings", None),
            ("could_not_read", "no_readings", None),
        }

    def test_empty_results_are_allowed(self, gw):
        assert gw.post("/gw/v1/cycles", cycle(results=[]), format="json").status_code == 202

    @pytest.mark.parametrize(
        "results",
        [
            [{"sensor_id": "s1", "outcome": "readings"}],
            [{"sensor_id": "s1", "outcome": "no_readings", "batch_id": "b1"}],
            [{"sensor_id": "s1", "outcome": "exploded"}],
            [{"sensor_id": "s1", "outcome": "no_readings"}, {"sensor_id": "s1", "outcome": "timeout"}],
            "nope",
        ],
    )
    def test_invalid_results_are_422(self, gw, results):
        assert gw.post("/gw/v1/cycles", cycle(results=results), format="json").status_code == 422
        assert not Cycle.objects.exists()

    def test_null_batch_id_counts_as_absent(self, gw):
        body = cycle(results=[{"sensor_id": "s2", "outcome": "no_readings", "batch_id": None}])
        assert gw.post("/gw/v1/cycles", body, format="json").status_code == 202

    def test_finished_before_started_is_422(self, gw):
        assert gw.post("/gw/v1/cycles", cycle(finished=(1, 11, 0)), format="json").status_code == 422

    def test_finished_more_than_5_minutes_ahead_is_422(self, gw):
        resp = gw.post("/gw/v1/cycles", cycle(finished=(1, 12, 6)), format="json")
        assert resp.status_code == 422
        assert resp.json()["error"] == "timestamp_in_future"

    def test_cycle_ids_are_per_gateway(self, gw, api):
        other = device(register_gateway(api, "g2"))
        assert gw.post("/gw/v1/cycles", cycle(), format="json").status_code == 202
        assert other.post("/gw/v1/cycles", cycle(results=[]), format="json").status_code == 202
