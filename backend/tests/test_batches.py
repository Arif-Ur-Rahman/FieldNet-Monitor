import pytest

from batches.models import Batch, Reading
from core import timeline
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0, second=0):
    from datetime import timedelta

    return (at(day, hour, minute) + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")


def reading(rid="r1", taken=(1, 11, 0), value=21.5, unit="C"):
    return {"reading_id": rid, "taken_at": iso(*taken), "value": value, "unit": unit}


def batch(sensor_id="s1", readings=None):
    return {"sensor_id": sensor_id, "readings": readings if readings is not None else [reading()]}


@pytest.fixture
def gw(api, clock_at):
    """Gateway g1 covering temperature sensor s1; rain sensor s2 also covered. Clock at day 1 12:00."""
    clock_at(1, 12)
    token = register_gateway(api)
    register_sensor(api, "s1", "temperature")
    register_sensor(api, "s2", "rain")
    set_coverage(api, "s1", ["g1"])
    set_coverage(api, "s2", ["g1"])
    return device(token)


@pytest.fixture
def put(gw):
    def put_(batch_id="b1", body=None, client=None):
        return (client or gw).put(f"/gw/v1/batches/{batch_id}", body if body is not None else batch(), format="json")

    return put_


def drain(api):
    assert api.post("/test/drain").status_code == 200


def state(api, batch_id="b1"):
    resp = api.get(f"/api/v1/batches/{batch_id}")
    assert resp.status_code == 200, resp.content
    return resp.json()


class TestPut:
    def test_stores_the_batch_as_received_without_processing_it(self, api, put):
        resp = put()
        assert resp.status_code == 202
        assert resp.json() == {"processing": "received", "attempts": 0, "accepted_count": 0, "quarantined": []}
        assert not Reading.objects.exists()

    def test_identical_repeat_is_200_and_changes_nothing(self, api, put):
        put()
        resp = put()
        assert resp.status_code == 200
        assert Batch.objects.count() == 1

    def test_identical_repeat_after_processing_returns_the_processed_state(self, api, put):
        put()
        drain(api)
        resp = put()
        assert resp.status_code == 200
        assert resp.json()["processing"] == "processed"

    def test_same_id_different_body_is_409(self, put):
        put()
        resp = put(body=batch(readings=[reading(value=99)]))
        assert resp.status_code == 409
        assert resp.json()["error"] == "batch_conflict"

    def test_same_id_from_another_gateway_is_409(self, api, put):
        put()
        other = device(register_gateway(api, "g2", "Gateway 2"))
        resp = put(client=other)
        assert resp.status_code == 409
        assert resp.json()["error"] == "batch_conflict"

    @pytest.mark.parametrize(
        "body",
        [{}, {"sensor_id": "s1"}, {"readings": []}, {"sensor_id": "s1", "readings": "nope"}, {"sensor_id": 5}],
    )
    def test_malformed_body_is_422(self, put, body):
        assert put(body=body).status_code == 422

    def test_unknown_token_is_401(self, put):
        assert put(client=device("nope")).status_code == 401

    def test_writes_a_received_timeline_entry(self, put):
        put()
        entry = timeline.entries("batch", "b1").get()
        assert (entry.axis, entry.from_value, entry.to_value, entry.effective_at) == (
            "processing",
            None,
            "received",
            at(1, 12),
        )


class TestProcessing:
    def test_valid_readings_are_accepted(self, api, put):
        put(body=batch(readings=[reading("r1", (1, 10)), reading("r2", (1, 11))]))
        drain(api)
        assert state(api) == {"processing": "processed", "attempts": 1, "accepted_count": 2, "quarantined": []}
        b = Batch.objects.get()
        assert b.resolved_at == at(1, 12)
        assert b.latest_accepted_taken_at == at(1, 11)
        r = Reading.objects.get(pk="r1")
        assert (r.sensor_id, r.gateway_id, r.taken_at, r.value, r.unit) == ("s1", "g1", at(1, 10), 21.5, "C")

    def test_nothing_is_processed_until_the_clock_moves_or_drains(self, api, put):
        put()
        assert state(api)["processing"] == "received"
        api.post("/test/clock", {"now": iso(1, 12, 1)}, format="json")
        assert state(api)["processing"] == "processed"

    def test_some_invalid_readings_make_it_partially_processed(self, api, put):
        readings = [
            reading("ok"),
            {"reading_id": "missing", "taken_at": iso(1, 11), "unit": "C"},
            reading("text", value="21.5"),
            reading("bool", value=True),
            reading("unit", unit="mm"),
            reading("future", taken=(1, 12, 5, 1)),
            reading("edge", taken=(1, 12, 5)),
            {"reading_id": "when", "taken_at": "yesterday", "value": 1, "unit": "C"},
            {"taken_at": iso(1, 11), "value": 1, "unit": "C"},
            "not an object",
        ]
        put(body=batch(readings=readings))
        drain(api)
        s = state(api)
        assert s["processing"] == "partially_processed"
        assert s["accepted_count"] == 2
        assert s["quarantined"] == [
            {"reading_id": "missing", "reason": "missing_field"},
            {"reading_id": "text", "reason": "invalid_value"},
            {"reading_id": "bool", "reason": "invalid_value"},
            {"reading_id": "unit", "reason": "wrong_unit"},
            {"reading_id": "future", "reason": "timestamp_in_future"},
            {"reading_id": "when", "reason": "invalid_taken_at"},
            {"reading_id": None, "reason": "missing_field"},
            {"reading_id": None, "reason": "missing_field"},
        ]
        assert set(Reading.objects.values_list("pk", flat=True)) == {"ok", "edge"}

    @pytest.mark.parametrize(("sensor", "unit"), [("s1", "C"), ("s2", "mm")])
    def test_units_follow_the_sensor_type(self, api, put, sensor, unit):
        put(body=batch(sensor, [reading(unit=unit)]))
        drain(api)
        assert state(api)["processing"] == "processed"

    def test_every_reading_invalid_quarantines_the_batch(self, api, put):
        put(body=batch(readings=[reading("a", unit="mm"), reading("b", value=None)]))
        drain(api)
        s = state(api)
        assert (s["processing"], s["accepted_count"]) == ("quarantined", 0)
        assert [q["reason"] for q in s["quarantined"]] == ["wrong_unit", "missing_field"]
        assert Batch.objects.get().reason == "all_invalid"

    def test_unknown_sensor_quarantines_the_batch(self, api, put):
        put(body=batch("ghost", [reading("a"), reading("b")]))
        drain(api)
        s = state(api)
        assert s["processing"] == "quarantined"
        assert s["quarantined"] == [
            {"reading_id": "a", "reason": "unknown_sensor"},
            {"reading_id": "b", "reason": "unknown_sensor"},
        ]
        assert not Reading.objects.exists()

    def test_empty_batch_is_quarantined(self, api, put):
        put(body=batch(readings=[]))
        drain(api)
        assert state(api)["processing"] == "quarantined"
        assert Batch.objects.get().reason == "empty_batch"

    def test_batch_for_a_sensor_the_gateway_does_not_cover_is_accepted(self, api, put):
        register_sensor(api, "s3")
        put(body=batch("s3"))
        drain(api)
        assert state(api)["processing"] == "processed"

    def test_writes_timeline_entries_at_the_processing_time(self, api, put):
        put()
        api.post("/test/clock", {"now": iso(2)}, format="json")
        entries = [(e.from_value, e.to_value, e.effective_at) for e in timeline.entries("batch", "b1")]
        # Processed at its due time (received), not at the clock jump.
        assert entries == [(None, "received", at(1, 12)), ("received", "processed", at(1, 12))]


class TestDuplicates:
    def test_same_reading_again_is_ignored(self, api, put):
        put("b1", batch(readings=[reading("r1")]))
        put("b2", batch(readings=[reading("r1"), reading("r2")]))
        drain(api)
        assert state(api, "b2") == {"processing": "processed", "attempts": 1, "accepted_count": 1, "quarantined": []}
        assert Reading.objects.get(pk="r1").batch_id == "b1"

    def test_same_id_different_content_is_conflicting_duplicate(self, api, put):
        put("b1", batch(readings=[reading("r1", value=1)]))
        put("b2", batch(readings=[reading("r1", value=2), reading("r2")]))
        drain(api)
        s = state(api, "b2")
        assert s["processing"] == "partially_processed"
        assert s["quarantined"] == [{"reading_id": "r1", "reason": "conflicting_duplicate"}]
        assert Reading.objects.get(pk="r1").value == 1

    def test_duplicate_inside_one_batch(self, api, put):
        put(body=batch(readings=[reading("r1", value=1), reading("r1", value=1), reading("r1", value=2)]))
        drain(api)
        s = state(api)
        assert s["accepted_count"] == 1
        assert s["quarantined"] == [{"reading_id": "r1", "reason": "conflicting_duplicate"}]

    def test_the_first_processed_version_wins(self, api, put, clock_at):
        # b2 is received first, so it is processed first, whatever the ids.
        put("b2", batch(readings=[reading("r1", value=2)]))
        clock_at(1, 12, 1)
        put("b1", batch(readings=[reading("r1", value=1)]))
        drain(api)
        assert Reading.objects.get(pk="r1").value == 2
        assert state(api, "b1")["processing"] == "quarantined"


class TestRetries:
    def test_failed_attempts_retry_with_backoff_then_succeed(self, api, put):
        api.post("/test/faults", {"processing_failures": 2}, format="json")
        put()
        drain(api)
        assert (state(api)["processing"], state(api)["attempts"]) == ("retrying", 1)
        assert Batch.objects.get().next_attempt_at == at(1, 12, 1)
        # Attempt 2 at 12:01 fails and waits 2 minutes; attempt 3 at 12:03 succeeds.
        api.post("/test/clock", {"now": iso(1, 12, 2)}, format="json")
        assert (state(api)["processing"], state(api)["attempts"]) == ("retrying", 2)
        api.post("/test/clock", {"now": iso(1, 13)}, format="json")
        assert state(api) == {"processing": "processed", "attempts": 3, "accepted_count": 1, "quarantined": []}
        assert Batch.objects.get().resolved_at == at(1, 12, 3)

    def test_a_clock_jump_runs_every_due_retry(self, api, put):
        api.post("/test/faults", {"processing_failures": 3}, format="json")
        put()
        api.post("/test/clock", {"now": iso(2)}, format="json")
        assert state(api)["attempts"] == 4
        # Attempts at 12:00, 12:01, 12:03 fail; 12:07 succeeds.
        assert Batch.objects.get().resolved_at == at(1, 12, 7)

    def test_fifth_failure_quarantines_with_processing_failed(self, api, put):
        api.post("/test/faults", {"processing_failures": 5}, format="json")
        put(body=batch(readings=[reading("a"), reading("b")]))
        api.post("/test/clock", {"now": iso(2)}, format="json")
        s = state(api)
        assert (s["processing"], s["attempts"], s["accepted_count"]) == ("quarantined", 5, 0)
        assert s["quarantined"] == [
            {"reading_id": "a", "reason": "processing_failed"},
            {"reading_id": "b", "reason": "processing_failed"},
        ]
        # Attempts at 12:00, 12:01, 12:03, 12:07 and 12:15.
        assert Batch.objects.get().resolved_at == at(1, 12, 15)
        assert not Reading.objects.exists()

    def test_a_crash_mid_attempt_leaves_nothing_behind(self, api, put, monkeypatch):
        from batches import processing

        real_check = processing.check
        calls = {"n": 0}

        def crash_on_second_reading(raw, sensor, batch):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("disk on fire")
            return real_check(raw, sensor, batch)

        monkeypatch.setattr(processing, "check", crash_on_second_reading)
        put(body=batch(readings=[reading("a"), reading("b")]))
        drain(api)
        assert (state(api)["processing"], state(api)["accepted_count"]) == ("retrying", 0)
        assert not Reading.objects.exists()
        api.post("/test/clock", {"now": iso(1, 12, 1)}, format="json")
        assert state(api) == {"processing": "processed", "attempts": 2, "accepted_count": 2, "quarantined": []}

    def test_timeline_records_retrying_once_then_the_outcome(self, api, put):
        api.post("/test/faults", {"processing_failures": 2}, format="json")
        put()
        api.post("/test/clock", {"now": iso(2)}, format="json")
        entries = [(e.from_value, e.to_value, e.effective_at) for e in timeline.entries("batch", "b1")]
        assert entries == [
            (None, "received", at(1, 12)),
            ("received", "retrying", at(1, 12)),
            ("retrying", "processed", at(1, 12, 3)),
        ]


class TestGet:
    def test_unknown_batch_is_404(self, api, test_mode):
        resp = api.get("/api/v1/batches/nope")
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"


class TestMatchingCycles:
    def cycle(self, gw):
        body = {
            "cycle_id": "c1",
            "started_at": iso(1, 11, 50),
            "finished_at": iso(1, 11, 55),
            "session": "ok",
            "results": [{"sensor_id": "s1", "outcome": "readings", "batch_id": "b1"}],
        }
        assert gw.post("/gw/v1/cycles", body, format="json").status_code == 202

    def matched(self):
        from batches import services
        from gateways.models import CycleResult

        result = CycleResult.objects.get()
        return services.find([result.batch_id]).get(result.batch_id)

    def test_cycle_first_then_batch(self, api, gw, put):
        self.cycle(gw)
        assert self.matched() is None
        put()
        drain(api)
        assert self.matched().processing == "processed"

    def test_batch_first_then_cycle(self, api, gw, put):
        put()
        drain(api)
        self.cycle(gw)
        assert self.matched().processing == "processed"
