"""Every change of any axis appends a timeline entry: one full story, every entry checked."""

import pytest

from core import timeline
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage

pytestmark = pytest.mark.django_db


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


def entries(entity_type, entity_id):
    return [
        (e.kind, e.axis, e.from_value, e.to_value, e.effective_at) for e in timeline.entries(entity_type, entity_id)
    ]


@pytest.fixture
def story(api, clock_at):
    """G covers S. G connects, S activates, G is stopped and collects anyway, resumes, and is suspended."""
    clock_at(0, 8)
    g = device(register_gateway(api, "G"))
    register_sensor(api, "S")
    set_coverage(api, "S", ["G"])

    def cycle(n, hour, minute=0):
        body = {
            "cycle_id": f"c{n}",
            "started_at": iso(0, hour, minute),
            "finished_at": iso(0, hour, minute),
            "session": "ok",
            "results": [{"sensor_id": "S", "outcome": "no_readings"}],
        }
        assert g.post("/gw/v1/cycles", body, format="json").status_code == 202

    def batch(batch_id, hour, minute=0):
        body = {
            "sensor_id": "S",
            "readings": [{"reading_id": f"{batch_id}-r", "taken_at": iso(0, hour, minute), "value": 1, "unit": "C"}],
        }
        assert g.put(f"/gw/v1/batches/{batch_id}", body, format="json").status_code == 202
        api.post("/test/drain")

    def act(action, reason=None):
        body = {"action": action} | ({"reason": reason} if reason else {})
        assert api.post("/api/v1/gateways/G/actions", body, format="json").status_code == 200

    def ack(hour, minute):
        [command] = g.get("/gw/v1/commands").json()["commands"]
        body = {"acked_at": iso(0, hour, minute)}
        assert g.post(f"/gw/v1/commands/{command['command_id']}/ack", body, format="json").status_code == 204

    cycle(1, 8)  # G connects; S's coverage and collection follow
    clock_at(0, 9)
    batch("b1", 9)  # S's first reading
    clock_at(0, 9, 30)
    batch("b0", 8, 30)  # a reading taken earlier arrives late: a correction
    clock_at(0, 10)
    act("stop")
    clock_at(0, 10, 1)
    ack(10, 1)
    clock_at(0, 11)
    batch("b2", 10, 30)  # collected while stopped: flag
    clock_at(0, 12)
    act("resume")
    ack(12, 0)
    clock_at(0, 13)
    act("suspend", "site visit")
    return api


def test_gateway_timeline(story):
    assert entries("gateway", "G") == [
        ("transition", "status", "new", "connected", at(0, 8)),
        ("action", None, None, None, at(0, 10)),
        ("transition", "command_state", "running", "stop_pending", at(0, 10)),
        ("ack", None, None, None, at(0, 10, 1)),
        ("transition", "command_state", "stop_pending", "stopped", at(0, 10, 1)),
        ("flag", "flags", None, "collecting_after_stop", at(0, 10, 30)),
        ("action", None, None, None, at(0, 12)),
        ("transition", "command_state", "stopped", "resume_pending", at(0, 12)),
        ("ack", None, None, None, at(0, 12)),
        ("flag", "flags", "collecting_after_stop", None, at(0, 12)),
        ("transition", "command_state", "resume_pending", "running", at(0, 12)),
        ("action", None, None, None, at(0, 13)),
        ("transition", "status", "connected", "suspended", at(0, 13)),
    ]


def test_sensor_timeline(story):
    assert entries("sensor", "S") == [
        ("transition", "coverage", "none", "recoverable", at(0, 8)),
        ("transition", "coverage", "recoverable", "available", at(0, 8)),
        ("transition", "collection", "not_checked", "no_readings", at(0, 8)),
        ("transition", "lifecycle", "pending", "active", at(0, 9)),
        ("transition", "collection", "no_readings", "readings", at(0, 9)),
        # The 08:30 reading moves activation earlier: one correction, the 09:00 entry stays.
        ("correction", "lifecycle", "active", "active", at(0, 8, 30)),
        ("transition", "coverage", "available", "stopped", at(0, 10, 1)),
        ("transition", "collection", "readings", "collection_stopped", at(0, 10, 1)),
        ("transition", "coverage", "stopped", "available", at(0, 12)),
        ("transition", "collection", "collection_stopped", "readings", at(0, 12)),
        ("transition", "coverage", "available", "none", at(0, 13)),
        ("transition", "lifecycle", "active", "retired", at(0, 13)),
        ("transition", "collection", "readings", "not_checked", at(0, 13)),
    ]
    correction = [e for e in timeline.entries("sensor", "S") if e.kind == "correction"][0]
    assert correction.evidence_ids == ["batch-b0"]
    assert [(t["to"], t["at"]) for t in correction.detail["transitions"]] == [("active", iso(0, 8, 30))]


def test_batch_timeline(story):
    assert entries("batch", "b2") == [
        ("transition", "processing", None, "received", at(0, 11)),
        ("transition", "processing", "received", "processed", at(0, 11)),
    ]


def test_every_kind_but_rule_change_appears(story):
    kinds = {e[0] for e in entries("gateway", "G") + entries("sensor", "S")}
    assert kinds == {"transition", "correction", "action", "ack", "flag"}
