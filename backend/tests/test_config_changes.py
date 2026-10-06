"""Changing thresholds: a new version from now on, rule_change entries, and only later behaviour moves."""

import pytest

from core import timeline
from core.models import ConfigVersion
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db

DEFAULTS = {
    "quiet_days_before_dormant": 14,
    "dormant_wait_hours": 336,
    "sampling_window_hours": 72,
    "sampling_cycles_before_retired": 2,
    "stale_after_hours": 12,
    "command_timeout_minutes": 10,
    "batch_deadline_hours": 24,
}


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


def put(api, body):
    return api.put("/api/v1/config", body, format="json")


def move(api, day, hour=0, minute=0):
    """Set the test clock and run everything due (the clock_at fixture only sets it)."""
    assert api.post("/test/clock", {"now": iso(day, hour, minute)}, format="json").status_code == 200


def kinds(entity_type, entity_id, kind):
    return [e for e in timeline.entries(entity_type, entity_id) if e.kind == kind]


class TestEndpoint:
    def test_defaults(self, api, clock_at):
        clock_at(1)
        assert api.get("/api/v1/config").json() == DEFAULTS | {"effective_from": None}

    def test_change_takes_effect_now_and_keeps_the_rest(self, api, clock_at):
        clock_at(3, 9)
        resp = put(api, {"quiet_days_before_dormant": 7, "stale_after_hours": 6})
        assert resp.status_code == 200
        expected = DEFAULTS | {"quiet_days_before_dormant": 7, "stale_after_hours": 6, "effective_from": iso(3, 9)}
        assert resp.json() == expected
        assert api.get("/api/v1/config").json() == expected
        clock_at(4)
        assert put(api, {"stale_after_hours": 8}).json()["quiet_days_before_dormant"] == 7
        assert ConfigVersion.objects.count() == 2

    def test_same_values_record_nothing(self, api, clock_at):
        clock_at(1)
        register_sensor(api, "s1")
        assert put(api, {"quiet_days_before_dormant": 14}).json()["effective_from"] is None
        assert put(api, {}).status_code == 200
        assert ConfigVersion.objects.count() == 0
        assert kinds("sensor", "s1", "rule_change") == []

    @pytest.mark.parametrize(
        "body",
        [{"quiet_days_before_dormant": 0}, {"stale_after_hours": -1}, {"sampling_window_hours": "long"}, {"speed": 1}],
    )
    def test_invalid_is_422(self, api, clock_at, body):
        clock_at(1)
        resp = put(api, body)
        assert resp.status_code == 422
        assert resp.json()["error"] == "invalid_body"
        assert ConfigVersion.objects.count() == 0


class TestRuleChangeEntries:
    @pytest.fixture
    def fleet(self, api, clock_at):
        clock_at(1)
        register_gateway(api, "g1")
        register_sensor(api, "s1")
        set_coverage(api, "s1", ["g1"])
        clock_at(2)
        return api

    def test_a_sensor_threshold_writes_on_sensors(self, fleet):
        put(fleet, {"quiet_days_before_dormant": 7})
        [entry] = kinds("sensor", "s1", "rule_change")
        assert (entry.effective_at, entry.rule) == (at(2), "config_changed")
        assert entry.detail == {"changed": {"quiet_days_before_dormant": [14, 7]}}
        assert kinds("gateway", "g1", "rule_change") == []

    def test_a_gateway_threshold_writes_on_gateways(self, fleet):
        put(fleet, {"stale_after_hours": 6})
        [entry] = kinds("gateway", "g1", "rule_change")
        assert entry.detail == {"changed": {"stale_after_hours": [12, 6]}}
        assert kinds("sensor", "s1", "rule_change") == []

    def test_shown_in_the_timeline_api(self, fleet):
        put(fleet, {"stale_after_hours": 6})
        assert fleet.get("/api/v1/gateways/g1/timeline").json()[-1]["kind"] == "rule_change"


class TestOnlyLaterBehaviourMoves:
    @pytest.fixture
    def connected(self, api, clock_at):
        """g1 connected by a cycle at day 1 08:00, covering s1."""
        clock_at(1, 8)
        g1 = device(register_gateway(api, "g1"))
        register_sensor(api, "s1")
        set_coverage(api, "s1", ["g1"])
        body = {
            "cycle_id": "c1",
            "started_at": iso(1, 8),
            "finished_at": iso(1, 8),
            "session": "ok",
            "results": [{"sensor_id": "s1", "outcome": "no_readings"}],
        }
        assert g1.post("/gw/v1/cycles", body, format="json").status_code == 202
        return api

    def test_a_shorter_stale_threshold_already_passed_applies_at_the_change(self, connected, clock_at):
        move(connected, 1, 10)
        put(connected, {"stale_after_hours": 1})
        g = connected.get("/api/v1/gateways/g1").json()
        assert (g["status"], g["status_since"]) == ("stale", iso(1, 10))

    def test_a_longer_stale_threshold_extends_the_wait(self, connected, clock_at):
        move(connected, 1, 10)
        put(connected, {"stale_after_hours": 24})
        move(connected, 1, 21)
        assert connected.get("/api/v1/gateways/g1").json()["status"] == "connected"
        move(connected, 3)
        g = connected.get("/api/v1/gateways/g1").json()
        assert (g["status"], g["status_since"]) == ("stale", iso(2, 8))

    def test_shortening_the_quiet_threshold_mid_run(self, api, clock_at):
        """S active since day 0 with quiet days 1-5; the threshold drops to 3 on day 6 at 08:00."""
        clock_at(0, 6)
        g = device(register_gateway(api, "G"))
        register_sensor(api, "S")
        set_coverage(api, "S", ["G"])
        n = 0
        for day in range(0, 7):
            for hour in (6, 12, 18):
                if (day, hour) > (6, 6):
                    break
                move(api, day, hour)
                n += 1
                outcome = (
                    {"sensor_id": "S", "outcome": "readings", "batch_id": "b0"}
                    if (day, hour) == (0, 12)
                    else ({"sensor_id": "S", "outcome": "no_readings"})
                )
                body = {
                    "cycle_id": f"c{n}",
                    "started_at": iso(day, hour),
                    "finished_at": iso(day, hour),
                    "session": "ok",
                    "results": [outcome],
                }
                assert g.post("/gw/v1/cycles", body, format="json").status_code == 202
                if (day, hour) == (0, 12):
                    readings = [{"reading_id": "r0", "taken_at": iso(0, 12), "value": 1, "unit": "C"}]
                    g.put("/gw/v1/batches/b0", {"sensor_id": "S", "readings": readings}, format="json")
                    api.post("/test/drain")
        move(api, 6, 8)
        s = api.get("/api/v1/sensors/S").json()
        assert (s["lifecycle"], s["quiet_checked_days"]) == ("active", 5)

        put(api, {"quiet_days_before_dormant": 3})
        # Already past 3, but the threshold acts when a day completes: nothing changes now, nothing is corrected.
        assert api.get("/api/v1/sensors/S").json()["lifecycle"] == "active"
        move(api, 7)
        s = api.get("/api/v1/sensors/S").json()
        assert (s["lifecycle"], s["lifecycle_since"], s["quiet_checked_days"]) == ("dormant", iso(7), 6)
        assert kinds("sensor", "S", "correction") == []
        lifecycle = [(e.kind, e.to_value) for e in timeline.entries("sensor", "S") if e.axis == "lifecycle"]
        assert lifecycle == [("transition", "active"), ("transition", "dormant")]
