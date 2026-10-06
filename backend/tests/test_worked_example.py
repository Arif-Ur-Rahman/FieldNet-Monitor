"""The brief's worked example and its three variations, end to end through /gw/v1 and /test/clock.

Sensor S is covered only by gateway G, which reports S once a day at 12:00 UTC.
G also sends keep-alive cycles for a second sensor, S2, at 04:00 and 20:00, so
it never goes 12 hours without qualifying evidence. (With one cycle a day, the
12-hour stale rule would make G stale every night, which the example ignores.)
S itself only ever appears in the 12:00 cycle, as in the brief.
"""

import pytest

from core import timeline
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db

SLOTS = (4, 12, 20)


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


class Example:
    def __init__(self, api):
        self.api = api
        self.n = 0
        self.position = (0, 0)  # the next (day, hour) slot not yet played
        self.clock(0)
        self.g = device(register_gateway(api, "G", "Gateway G"))
        register_sensor(api, "S")
        register_sensor(api, "S2")
        set_coverage(api, "S", ["G"])
        set_coverage(api, "S2", ["G"])

    def clock(self, day, hour=0, minute=0):
        resp = self.api.post("/test/clock", {"now": iso(day, hour, minute)}, format="json")
        assert resp.status_code == 200, resp.content

    def cycle(self, day, hour, s_result=None, session="ok"):
        self.n += 1
        results = [{"sensor_id": "S2", "outcome": "no_readings"}]
        if s_result is not None:
            results.append(s_result)
        body = {
            "cycle_id": f"c{self.n}",
            "started_at": iso(day, hour),
            "finished_at": iso(day, hour),
            "session": session,
            "results": results,
        }
        assert self.g.post("/gw/v1/cycles", body, format="json").status_code == 202

    def batch(self, batch_id, taken):
        body = {
            "sensor_id": "S",
            "readings": [{"reading_id": f"{batch_id}-r", "taken_at": iso(*taken), "value": 21.0, "unit": "C"}],
        }
        assert self.g.put(f"/gw/v1/batches/{batch_id}", body, format="json").status_code == 202

    def play(self, until_day, until_hour=0, *, s=None, silent=()):
        """Play every slot before (until_day, until_hour), then set the clock there.

        s(day) gives S's 12:00 result (default no_readings; None for no result).
        Days in `silent` send nothing at all.
        """
        s = s or (lambda day: {"sensor_id": "S", "outcome": "no_readings"})
        day, _ = self.position
        while (day, 0) < (until_day, until_hour + 1):
            for hour in SLOTS:
                if (day, hour) < self.position or (day, hour) >= (until_day, until_hour):
                    continue
                self.clock(day, hour)
                if day not in silent:
                    self.cycle(day, hour, s(day) if hour == 12 else None)
            day += 1
        self.position = (until_day, until_hour)
        self.clock(until_day, until_hour)

    def start(self):
        """Day 0, 12:00: readings; the batch is processed at 12:01."""
        self.play(0, 12)
        self.cycle(0, 12, {"sensor_id": "S", "outcome": "readings", "batch_id": "b0"})
        self.clock(0, 12, 1)
        self.batch("b0", (0, 12))
        self.position = (0, 13)
        self.clock(0, 12, 1)

    def sensor(self):
        return self.api.get("/api/v1/sensors/S").json()

    def lifecycle(self):
        return [
            (e.kind, e.to_value, (e.detail or {}).get("reason"), e.effective_at)
            for e in timeline.entries("sensor", "S")
            if e.axis == "lifecycle"
        ]


@pytest.fixture
def ex(api, test_mode):
    return Example(api)


def state(s):
    return (s["lifecycle"], s["lifecycle_reason"], s["lifecycle_since"])


class TestWorkedExample:
    def test_the_full_run(self, ex):
        ex.start()
        s = ex.sensor()
        assert state(s) == ("active", None, iso(0, 12))

        for day in range(1, 15):
            ex.play(day + 1)
            assert ex.sensor()["quiet_checked_days"] == day

        s = ex.sensor()  # day 15, 00:00: day 14 completes
        assert state(s) == ("dormant", None, iso(15))
        assert s["next_evaluation_at"] == iso(29)

        ex.play(29)
        s = ex.sensor()
        assert (state(s), s["next_evaluation_at"]) == (("sampling", None, iso(29)), iso(32))

        ex.play(32)
        s = ex.sensor()
        assert (state(s), s["sampling_cycles_done"], s["next_evaluation_at"]) == (
            ("dormant", None, iso(32)),
            1,
            iso(46),
        )

        ex.play(46)
        assert state(ex.sensor()) == ("sampling", None, iso(46))

        ex.play(49)
        s = ex.sensor()
        assert (state(s), s["sampling_cycles_done"], s["next_evaluation_at"]) == (
            ("retired", "no_readings", iso(49)),
            2,
            None,
        )
        assert ex.lifecycle() == [
            ("transition", "active", None, at(0, 12)),
            ("transition", "dormant", None, at(15)),
            ("transition", "sampling", None, at(29)),
            ("transition", "dormant", None, at(32)),
            ("transition", "sampling", None, at(46)),
            ("transition", "retired", "no_readings", at(49)),
        ]


class TestDisconnectionMidWindow:
    """G reports auth_failed on day 30 at 12:00 and sends a good cycle on day 37 at 12:00."""

    def test_window_pauses_with_36_hours_left_and_ends_on_day_39(self, ex):
        ex.start()
        ex.play(30, 12)
        ex.cycle(30, 12, {"sensor_id": "S", "outcome": "no_readings"}, session="auth_failed")
        ex.position = (30, 13)
        assert ex.api.get("/api/v1/gateways/G").json()["status"] == "disconnected"

        ex.play(33, silent=range(30, 37))
        s = ex.sensor()
        # Paused: still sampling, no next evaluation, and collection shows not_checked.
        assert (s["lifecycle"], s["lifecycle_since"], s["next_evaluation_at"]) == ("sampling", iso(29), None)
        assert (s["coverage"], s["collection"]) == ("recoverable", "not_checked")

        ex.play(37, 12, silent=range(30, 38))  # nothing at all until the good cycle
        ex.cycle(37, 12, {"sensor_id": "S", "outcome": "no_readings"})
        ex.position = (37, 13)
        s = ex.sensor()
        assert (s["lifecycle"], s["next_evaluation_at"], s["coverage"]) == ("sampling", iso(39), "available")

        ex.play(38, 23)
        assert ex.sensor()["lifecycle"] == "sampling"
        ex.play(39)
        s = ex.sensor()
        assert (state(s), s["sampling_cycles_done"]) == (("dormant", None, iso(39)), 1)


class TestLateReading:
    """On day 20, G uploads a batch holding a reading taken on day 9."""

    def test_correction_from_dormant_to_active_and_the_day_15_entry_stays(self, ex):
        ex.start()
        ex.play(20, 9)
        assert state(ex.sensor()) == ("dormant", None, iso(15))

        ex.batch("late", (9, 8))
        assert ex.api.post("/test/drain").status_code == 200
        s = ex.sensor()
        # Days 10-19 are 10 quiet days: active, with every later timer moved.
        assert (state(s), s["quiet_checked_days"], s["next_evaluation_at"]) == (("active", None, iso(0, 12)), 10, None)
        assert ex.lifecycle() == [
            ("transition", "active", None, at(0, 12)),
            ("transition", "dormant", None, at(15)),
            ("correction", "active", None, at(15)),
        ]
        [correction] = [e for e in timeline.entries("sensor", "S") if e.kind == "correction"]
        assert (correction.from_value, correction.to_value, correction.evidence_ids) == (
            "dormant",
            "active",
            ["batch-late"],
        )

        # It goes dormant again when day 23 completes: the 14th quiet day since day 9.
        ex.play(24)
        assert state(ex.sensor()) == ("dormant", None, iso(24))
        assert ex.lifecycle()[-1] == ("transition", "dormant", None, at(24))
