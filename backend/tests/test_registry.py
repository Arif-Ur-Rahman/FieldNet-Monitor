import pytest
from django.test import RequestFactory

from core.errors import Forbidden, Unauthorized
from gateways.auth import gateway_from_request
from gateways.models import Gateway
from tests.helpers import register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


class TestGatewayRegistration:
    def test_register_returns_token_and_initial_state(self, api, clock_at):
        clock_at(0)
        token = register_gateway(api)
        assert isinstance(token, str) and len(token) >= 32
        body = api.get("/api/v1/gateways/g1").json()
        assert body == {
            "gateway_id": "g1",
            "name": "Gateway 1",
            "status": "new",
            "status_since": "2026-01-01T00:00:00Z",
            "command_state": "running",
            "coverage_class": "recoverable",
            "last_heartbeat_at": None,
            "last_qualifying_at": None,
            "disconnected_since": None,
            "flags": [],
        }

    def test_token_is_not_stored_in_plain_text(self, api, clock_at):
        token = register_gateway(api)
        assert not Gateway.objects.filter(token_hash=token).exists()

    def test_duplicate_id_is_409(self, api, clock_at):
        register_gateway(api)
        resp = api.post("/api/v1/gateways", {"gateway_id": "g1", "name": "again"}, format="json")
        assert resp.status_code == 409
        assert resp.json()["error"] == "duplicate_gateway"

    @pytest.mark.parametrize("body", [{}, {"gateway_id": "g1"}, {"name": "x"}, {"gateway_id": "", "name": "x"}])
    def test_invalid_body_is_422(self, api, clock_at, body):
        resp = api.post("/api/v1/gateways", body, format="json")
        assert resp.status_code == 422
        assert set(resp.json()) == {"error", "detail"}

    def test_malformed_json_is_422(self, api, clock_at):
        resp = api.post("/api/v1/gateways", "{not json", content_type="application/json")
        assert resp.status_code == 422

    def test_unknown_gateway_is_404(self, api, clock_at):
        assert api.get("/api/v1/gateways/nope").status_code == 404
        assert api.get("/api/v1/gateways/nope/timeline").status_code == 404


class TestGatewayAuth:
    def request(self, token):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token is not None else {}
        return RequestFactory().post("/gw/v1/heartbeat", **headers)

    def test_valid_token_identifies_gateway(self, api, clock_at):
        token = register_gateway(api)
        assert gateway_from_request(self.request(token), lock=False).gateway_id == "g1"

    @pytest.mark.parametrize("token", [None, "", "wrong"])
    def test_unknown_or_missing_token_is_401(self, api, clock_at, token):
        register_gateway(api)
        with pytest.raises(Unauthorized):
            gateway_from_request(self.request(token), lock=False)

    def test_retired_gateway_is_403(self, api, clock_at):
        token = register_gateway(api)
        Gateway.objects.filter(pk="g1").update(status="retired")
        with pytest.raises(Forbidden):
            gateway_from_request(self.request(token), lock=False)


class TestSensorRegistration:
    def test_register_pending_with_no_coverage(self, api, clock_at):
        clock_at(0, 6)
        body = register_sensor(api)
        assert body == {
            "sensor_id": "s1",
            "type": "temperature",
            "lifecycle": "pending",
            "lifecycle_reason": None,
            "lifecycle_since": "2026-01-01T06:00:00Z",
            "collection": "not_checked",
            "coverage": "none",
            "quiet_checked_days": 0,
            "sampling_cycles_done": 0,
            "next_evaluation_at": None,
        }
        assert api.get("/api/v1/sensors/s1").json() == body

    def test_duplicate_is_409_and_bad_type_is_422(self, api, clock_at):
        register_sensor(api)
        assert api.post("/api/v1/sensors", {"sensor_id": "s1", "type": "rain"}, format="json").status_code == 409
        assert api.post("/api/v1/sensors", {"sensor_id": "s2", "type": "humidity"}, format="json").status_code == 422

    def test_unknown_sensor_is_404(self, api, clock_at):
        assert api.get("/api/v1/sensors/nope").status_code == 404
        assert set_coverage(api, "nope", []).status_code == 404
        assert api.get("/api/v1/sensors/nope/timeline").status_code == 404


class TestCoverage:
    def test_assigning_a_new_gateway_gives_recoverable(self, api, clock_at):
        clock_at(1)
        register_gateway(api)
        register_sensor(api)
        resp = set_coverage(api, "s1", ["g1"])
        assert resp.status_code == 200
        assert resp.json()["coverage"] == "recoverable"
        entries = api.get("/api/v1/sensors/s1/timeline").json()
        assert [(e["kind"], e["axis"], e["from"], e["to"]) for e in entries] == [
            ("transition", "coverage", "none", "recoverable")
        ]
        assert entries[0]["effective_at"] == "2026-01-02T00:00:00Z"

    def test_best_class_wins(self, api, clock_at):
        register_gateway(api, "g1")
        register_gateway(api, "g2")
        register_sensor(api)
        Gateway.objects.filter(pk="g2").update(status="connected")
        assert set_coverage(api, "s1", ["g1", "g2"]).json()["coverage"] == "available"

    def test_replacing_with_empty_set_gives_none(self, api, clock_at):
        register_gateway(api)
        register_sensor(api)
        set_coverage(api, "s1", ["g1"])
        assert set_coverage(api, "s1", []).json()["coverage"] == "none"

    def test_reassigning_same_set_records_nothing(self, api, clock_at):
        register_gateway(api)
        register_sensor(api)
        set_coverage(api, "s1", ["g1"])
        set_coverage(api, "s1", ["g1", "g1"])
        assert len(api.get("/api/v1/sensors/s1/timeline").json()) == 1

    def test_unknown_gateway_is_404_and_changes_nothing(self, api, clock_at):
        register_gateway(api)
        register_sensor(api)
        resp = set_coverage(api, "s1", ["g1", "ghost"])
        assert resp.status_code == 404
        assert api.get("/api/v1/sensors/s1").json()["coverage"] == "none"

    def test_retired_gateway_is_409(self, api, clock_at):
        register_gateway(api)
        register_sensor(api)
        Gateway.objects.filter(pk="g1").update(status="retired")
        resp = set_coverage(api, "s1", ["g1"])
        assert resp.status_code == 409
        assert resp.json()["error"] == "gateway_retired"

    def test_spare_gateway_becomes_new_when_assigned(self, api, clock_at):
        clock_at(2)
        register_gateway(api)
        register_sensor(api)
        Gateway.objects.filter(pk="g1").update(status="spare")
        clock_at(3)
        set_coverage(api, "s1", ["g1"])
        gw = api.get("/api/v1/gateways/g1").json()
        assert (gw["status"], gw["status_since"]) == ("new", "2026-01-04T00:00:00Z")
        entries = api.get("/api/v1/gateways/g1/timeline").json()
        assert [(e["axis"], e["from"], e["to"], e["rule"]) for e in entries] == [
            ("status", "spare", "new", "sensor_assigned")
        ]

    def test_invalid_body_is_422(self, api, clock_at):
        register_sensor(api)
        assert api.put("/api/v1/sensors/s1/coverage", {"gateway_ids": "g1"}, format="json").status_code == 422
        assert api.put("/api/v1/sensors/s1/coverage", {}, format="json").status_code == 422


class TestDecommission:
    def test_decommission_is_terminal(self, api, clock_at):
        clock_at(5)
        register_sensor(api)
        resp = api.post("/api/v1/sensors/s1/actions", {"action": "decommission", "reason": "flooded"}, format="json")
        assert resp.status_code == 200
        body = resp.json()
        assert (body["lifecycle"], body["lifecycle_reason"], body["lifecycle_since"]) == (
            "decommissioned",
            "flooded",
            "2026-01-06T00:00:00Z",
        )
        again = api.post("/api/v1/sensors/s1/actions", {"action": "decommission", "reason": "x"}, format="json")
        assert again.status_code == 409

    def test_timeline_has_action_then_transition(self, api, clock_at):
        register_sensor(api)
        api.post("/api/v1/sensors/s1/actions", {"action": "decommission", "reason": "flooded"}, format="json")
        entries = api.get("/api/v1/sensors/s1/timeline").json()
        assert [(e["seq"], e["kind"], e["axis"], e["to"]) for e in entries] == [
            (1, "action", None, None),
            (2, "transition", "lifecycle", "decommissioned"),
        ]
        assert entries[0]["detail"] == {"reason": "flooded"}

    @pytest.mark.parametrize(
        "body",
        [{"action": "decommission"}, {"action": "decommission", "reason": ""}, {"action": "explode", "reason": "x"}],
    )
    def test_invalid_body_is_422(self, api, clock_at, body):
        register_sensor(api)
        assert api.post("/api/v1/sensors/s1/actions", body, format="json").status_code == 422

    def test_unknown_sensor_is_404(self, api, clock_at):
        resp = api.post("/api/v1/sensors/nope/actions", {"action": "decommission", "reason": "x"}, format="json")
        assert resp.status_code == 404
