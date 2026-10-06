"""Console API: lists with filters, dashboard counts, and the OpenAPI schema."""

import pytest
from django.core.management import call_command

from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


@pytest.fixture
def fleet(api, clock_at):
    """g1 connected covering s1 (active) and s2; g2 new; g3 suspended. Clock at day 1 12:00."""
    clock_at(1, 11)
    g1 = device(register_gateway(api, "g1"))
    register_gateway(api, "g2")
    register_gateway(api, "g3")
    for sid in ("s1", "s2", "s3"):
        register_sensor(api, sid)
    set_coverage(api, "s1", ["g1"])
    set_coverage(api, "s2", ["g1"])
    body = {
        "cycle_id": "c1",
        "started_at": iso(1, 11),
        "finished_at": iso(1, 11),
        "session": "ok",
        "results": [{"sensor_id": "s1", "outcome": "readings", "batch_id": "b1"}],
    }
    assert g1.post("/gw/v1/cycles", body, format="json").status_code == 202
    readings = [{"reading_id": "r1", "taken_at": iso(1, 11), "value": 1.0, "unit": "C"}]
    assert g1.put("/gw/v1/batches/b1", {"sensor_id": "s1", "readings": readings}, format="json").status_code == 202
    clock_at(1, 12)
    api.post("/test/drain")
    api.post("/api/v1/gateways/g3/actions", {"action": "suspend", "reason": "x"}, format="json")
    return api


class TestGatewayList:
    def test_every_gateway_in_the_detail_shape_ordered_by_id(self, fleet):
        resp = fleet.get("/api/v1/gateways")
        assert resp.status_code == 200
        gateways = resp.json()
        assert [g["gateway_id"] for g in gateways] == ["g1", "g2", "g3"]
        assert gateways[0] == fleet.get("/api/v1/gateways/g1").json()

    @pytest.mark.parametrize(
        ("query", "expected"),
        [("connected", ["g1"]), ("new,suspended", ["g2", "g3"]), ("stale", []), ("", ["g1", "g2", "g3"])],
    )
    def test_status_filter(self, fleet, query, expected):
        resp = fleet.get("/api/v1/gateways", {"status": query})
        assert [g["gateway_id"] for g in resp.json()] == expected

    def test_unknown_status_is_422(self, fleet):
        resp = fleet.get("/api/v1/gateways", {"status": "connected,sleepy"})
        assert resp.status_code == 422
        assert resp.json()["error"] == "invalid_filter"

    def test_empty_fleet(self, api, test_mode):
        assert api.get("/api/v1/gateways").json() == []


class TestSensorList:
    def test_every_sensor_in_the_detail_shape_ordered_by_id(self, fleet):
        sensors = fleet.get("/api/v1/sensors").json()
        assert [s["sensor_id"] for s in sensors] == ["s1", "s2", "s3"]
        assert sensors[0] == fleet.get("/api/v1/sensors/s1").json()

    @pytest.mark.parametrize(("query", "expected"), [("active", ["s1"]), ("pending,dormant", ["s2", "s3"])])
    def test_lifecycle_filter(self, fleet, query, expected):
        assert [s["sensor_id"] for s in fleet.get("/api/v1/sensors", {"lifecycle": query}).json()] == expected

    def test_unknown_lifecycle_is_422(self, fleet):
        assert fleet.get("/api/v1/sensors", {"lifecycle": "zombie"}).status_code == 422


class TestDashboard:
    def test_every_value_is_present_with_zero_counts(self, api, test_mode):
        d = api.get("/api/v1/dashboard").json()
        assert d["gateways"]["total"] == d["sensors"]["total"] == d["batches"]["total"] == 0
        assert set(d["gateways"]["status"]) == {
            "new",
            "spare",
            "connected",
            "stale",
            "disconnected",
            "suspended",
            "retired",
        }
        assert set(d["gateways"]["coverage_class"]) == {"available", "stopped", "recoverable", "dead"}
        assert set(d["sensors"]["collection"]) == {
            "readings",
            "no_readings",
            "could_not_read",
            "timed_out",
            "not_checked",
            "collection_stopped",
        }
        groups = [counts for group in d.values() for counts in group.values() if isinstance(counts, dict)]
        assert all(n == 0 for counts in groups for n in counts.values())

    def test_counts(self, fleet):
        d = fleet.get("/api/v1/dashboard").json()
        g = d["gateways"]
        assert g["total"] == 3
        assert (g["status"]["connected"], g["status"]["new"], g["status"]["suspended"]) == (1, 1, 1)
        assert g["command_state"]["running"] == 3
        assert g["coverage_class"] == {"available": 1, "stopped": 0, "recoverable": 1, "dead": 1}
        assert g["flags"] == {"collecting_after_stop": 0}
        s = d["sensors"]
        assert (s["total"], s["lifecycle"]["active"], s["lifecycle"]["pending"]) == (3, 1, 2)
        assert s["coverage"] == {"available": 2, "stopped": 0, "recoverable": 0, "none": 1}
        assert (s["collection"]["readings"], s["collection"]["not_checked"]) == (1, 2)
        assert d["batches"] == {
            "total": 1,
            "processing": {
                "received": 0,
                "processed": 1,
                "partially_processed": 0,
                "retrying": 0,
                "quarantined": 0,
            },
        }

    def test_retired_reasons(self, fleet):
        set_coverage(fleet, "s1", [])
        assert fleet.get("/api/v1/dashboard").json()["sensors"]["retired_reason"] == {
            "no_readings": 0,
            "no_live_coverage": 1,
        }


class TestOpenAPI:
    def test_schema_validates_without_warnings(self, tmp_path):
        call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "schema.yml"))

    def test_every_route_is_documented(self, api):
        paths = api.get("/api/schema/", HTTP_ACCEPT="application/json").json()["paths"]
        assert {
            "/api/v1/dashboard",
            "/api/v1/gateways",
            "/api/v1/gateways/{gateway_id}/actions",
            "/api/v1/sensors/{sensor_id}/coverage",
            "/api/v1/batches/{batch_id}",
            "/gw/v1/heartbeat",
            "/gw/v1/cycles",
            "/gw/v1/batches/{batch_id}",
            "/gw/v1/commands",
            "/gw/v1/commands/{command_id}/ack",
            "/test/clock",
        } <= set(paths)
        assert paths["/gw/v1/cycles"]["post"]["security"] == [{"gatewayToken": []}]

    def test_docs_page_renders(self, api):
        resp = api.get("/api/docs/")
        assert resp.status_code == 200
        assert b"swagger" in resp.content.lower()
