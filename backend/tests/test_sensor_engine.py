"""The sensor engine wired in: through the API and the test clock."""

import pytest

from core import timeline
from sensors.models import Sensor
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


class World:
    """Gateway G covering sensor S. G cycles every 6 hours so it stays connected.

    (The brief's example has G report once a day; by the 12-hour stale rule G would
    then go stale every night, which the example doesn't account for.)
    """

    def __init__(self, api):
        self.api = api
        self.api.post("/test/clock", {"now": iso(0)}, format="json")
        self.g = device(register_gateway(api, "G", "Gateway G"))
        register_sensor(api, "S")
        set_coverage(api, "S", ["G"])
        self.n = 0
        self.now = at(0)

    def clock(self, day, hour=0, minute=0):
        resp = self.api.post("/test/clock", {"now": iso(day, hour, minute)}, format="json")
        assert resp.status_code == 200, resp.content
        self.now = at(day, hour, minute)

    def cycle(self, day, hour, outcome="no_readings", batch_id=None):
        self.n += 1
        result = {"sensor_id": "S", "outcome": outcome} | ({"batch_id": batch_id} if batch_id else {})
        body = {
            "cycle_id": f"c{self.n}",
            "started_at": iso(day, hour),
            "finished_at": iso(day, hour),
            "session": "ok",
            "results": [result],
        }
        assert self.g.post("/gw/v1/cycles", body, format="json").status_code == 202

    def batch(self, batch_id, taken):
        body = {
            "sensor_id": "S",
            "readings": [{"reading_id": f"{batch_id}-r", "taken_at": iso(*taken), "value": 1.0, "unit": "C"}],
        }
        assert self.g.put(f"/gw/v1/batches/{batch_id}", body, format="json").status_code == 202
        assert self.api.post("/test/drain").status_code == 200

    def run_days(self, first, last, *, quiet=True):
        """Cycles at 00, 06, 12 and 18 on each day in [first, last]."""
        for day in range(first, last + 1):
            for hour in (0, 6, 12, 18):
                self.clock(day, hour)
                if quiet:
                    self.cycle(day, hour)

    def start(self):
        """Day 0 12:00: readings, the batch processed at 12:01."""
        self.clock(0, 12)
        self.cycle(0, 12, "readings", "b0")
        self.clock(0, 12, 1)
        self.batch("b0", (0, 12))
        self.clock(0, 18)
        self.cycle(0, 18)

    def sensor(self):
        return self.api.get("/api/v1/sensors/S").json()

    def lifecycle_entries(self):
        return [e for e in timeline.entries("sensor", "S") if e.axis == "lifecycle"]


@pytest.fixture
def world(api, test_mode):
    return World(api)


class TestForwardProgress:
    def test_first_reading_makes_it_active(self, world):
        world.start()
        s = world.sensor()
        assert (s["lifecycle"], s["lifecycle_since"], s["coverage"]) == ("active", iso(0, 12), "available")
        assert s["collection"] == "no_readings"  # the 18:00 cycle is the latest

    def test_quiet_days_count_and_it_goes_dormant_at_day_15(self, world):
        world.start()
        world.run_days(1, 14)
        s = world.sensor()
        assert (s["lifecycle"], s["quiet_checked_days"]) == ("active", 13)
        world.clock(15)
        s = world.sensor()
        assert (s["lifecycle"], s["lifecycle_since"], s["quiet_checked_days"]) == ("dormant", iso(15), 14)
        assert s["next_evaluation_at"] == iso(29)

    def test_a_clock_jump_records_each_transition_at_its_own_time(self, world):
        world.start()
        world.run_days(1, 14)
        world.clock(15)
        # Silence from here: G's last cycle was day 14 18:00, so it goes stale at day 15 06:00.
        world.clock(40)
        entries = [(e.kind, e.to_value, e.effective_at) for e in world.lifecycle_entries()]
        assert entries[:2] == [("transition", "active", at(0, 12)), ("transition", "dormant", at(15))]
        s = world.sensor()
        # Coverage went recoverable with G, so the dormant wait paused after 6 hours.
        assert (s["lifecycle"], s["coverage"], s["next_evaluation_at"]) == ("dormant", "recoverable", None)


class TestLateReadingCorrection:
    """Brief: on day 20, G uploads a batch holding a reading taken on day 9."""

    def test_correction_from_dormant_to_active(self, world):
        world.start()
        world.run_days(1, 19)
        world.clock(20)
        assert world.sensor()["lifecycle"] == "dormant"

        world.batch("late", (9, 8))
        s = world.sensor()
        assert (s["lifecycle"], s["quiet_checked_days"], s["lifecycle_since"]) == ("active", 10, iso(0, 12))

        entries = world.lifecycle_entries()
        kinds = [(e.kind, e.from_value, e.to_value) for e in entries]
        # The day-15 dormant entry stays; one correction records dormant → active.
        assert kinds == [
            ("transition", "pending", "active"),
            ("transition", "active", "dormant"),
            ("correction", "dormant", "active"),
        ]
        correction = entries[-1]
        assert correction.evidence_ids == ["batch-late"]
        assert correction.effective_at == at(15)
        assert correction.detail["previous"] == {"lifecycle": "dormant", "reason": None}
        assert correction.detail["corrected"] == {"lifecycle": "active", "reason": None}
        assert [t["to"] for t in correction.detail["transitions"]] == ["active"]

    def test_the_same_late_reading_again_records_nothing_more(self, world):
        world.start()
        world.run_days(1, 19)
        world.clock(20)
        world.batch("late", (9, 8))
        count = len(world.lifecycle_entries())
        world.api.post("/test/drain")
        world.clock(20, 1)
        assert len(world.lifecycle_entries()) == count

    def test_after_a_correction_forward_progress_appends_transitions(self, world):
        world.start()
        world.run_days(1, 19)
        world.clock(20)
        world.batch("late", (9, 8))
        world.run_days(20, 23)
        world.clock(24)
        entries = world.lifecycle_entries()
        assert [(e.kind, e.to_value, e.effective_at) for e in entries[-1:]] == [("transition", "dormant", at(24))]
        assert world.sensor()["lifecycle"] == "dormant"


class TestCoverage:
    def test_losing_all_coverage_retires_it_at_once(self, world, api):
        world.start()
        world.clock(1)
        set_coverage(api, "S", [])
        s = world.sensor()
        assert (s["lifecycle"], s["lifecycle_reason"], s["lifecycle_since"]) == ("retired", "no_live_coverage", iso(1))
        assert (s["coverage"], s["collection"]) == ("none", "not_checked")

    def test_regaining_coverage_makes_it_pending(self, world, api):
        world.start()
        world.clock(1)
        set_coverage(api, "S", [])
        world.clock(2)
        set_coverage(api, "S", ["G"])
        s = world.sensor()
        assert (s["lifecycle"], s["lifecycle_reason"], s["lifecycle_since"]) == ("pending", None, iso(2))

    def test_suspending_the_only_gateway_retires_it_at_once(self, world, api):
        world.start()
        world.clock(1)
        api.post("/api/v1/gateways/G/actions", {"action": "suspend", "reason": "x"}, format="json")
        s = world.sensor()
        assert (s["lifecycle"], s["lifecycle_reason"], s["coverage"]) == ("retired", "no_live_coverage", "none")

    def test_a_pending_sensor_stays_pending_without_coverage(self, api, test_mode):
        api.post("/test/clock", {"now": iso(0)}, format="json")
        register_sensor(api, "lonely")
        api.post("/test/clock", {"now": iso(30)}, format="json")
        assert api.get("/api/v1/sensors/lonely").json()["lifecycle"] == "pending"


class TestCollection:
    def test_collection_changes_are_recorded(self, world):
        world.start()
        entries = [(e.from_value, e.to_value) for e in timeline.entries("sensor", "S") if e.axis == "collection"]
        assert entries == [("not_checked", "readings"), ("readings", "no_readings")]

    def test_collection_ages_out_in_tick(self, world, api):
        # G keeps cycling for another sensor, so it stays connected; S gets no more outcomes.
        register_sensor(api, "S2")
        set_coverage(api, "S2", ["G"])
        world.start()
        for day, hour in [(1, 0), (1, 6), (1, 12)]:
            world.clock(day, hour)
            world.n += 1
            body = {
                "cycle_id": f"c{world.n}",
                "started_at": iso(day, hour),
                "finished_at": iso(day, hour),
                "session": "ok",
                "results": [{"sensor_id": "S2", "outcome": "no_readings"}],
            }
            assert world.g.post("/gw/v1/cycles", body, format="json").status_code == 202
        world.clock(1, 17, 59)
        assert world.sensor()["collection"] == "no_readings"
        world.clock(1, 20)
        # S's last outcome (day 0 18:00) aged out at day 1 18:00, recorded at that time by tick.
        assert (world.sensor()["coverage"], world.sensor()["collection"]) == ("available", "not_checked")
        last = [e for e in timeline.entries("sensor", "S") if e.axis == "collection"][-1]
        assert (last.from_value, last.to_value, last.effective_at) == ("no_readings", "not_checked", at(1, 18))


class TestDecommission:
    def test_still_terminal_through_the_engine(self, world, api):
        world.start()
        world.clock(1)
        resp = api.post("/api/v1/sensors/S/actions", {"action": "decommission", "reason": "flooded"}, format="json")
        assert resp.json()["lifecycle"] == "decommissioned"
        world.run_days(1, 2)
        s = world.sensor()
        assert (s["lifecycle"], s["lifecycle_reason"], s["lifecycle_since"]) == ("decommissioned", "flooded", iso(1))


def test_reconcile_at_tracks_the_next_due_time(world):
    world.start()
    assert Sensor.objects.get().reconcile_at == at(1)  # the next midnight while active


def test_coverage_changes_at_one_instant_end_on_the_last(api, test_mode):
    """Sensor, assignment and the gateway's first good cycle all at once: coverage ends available."""
    api.post("/test/clock", {"now": iso(0, 8)}, format="json")
    g = device(register_gateway(api, "G1"))
    register_sensor(api, "S1")
    set_coverage(api, "S1", ["G1"])
    body = {
        "cycle_id": "c1",
        "started_at": iso(0, 8),
        "finished_at": iso(0, 8),
        "session": "ok",
        "results": [{"sensor_id": "S1", "outcome": "no_readings"}],
    }
    assert g.post("/gw/v1/cycles", body, format="json").status_code == 202
    s = api.get("/api/v1/sensors/S1").json()
    assert (s["coverage"], s["collection"]) == ("available", "no_readings")
