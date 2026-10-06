"""Brief rules that no other test pinned down exactly. See docs/conformance.md for the full rule-to-test table."""

import itertools
import re
from pathlib import Path

import pytest

from batches.models import Batch
from core import timeline
from gateways.coverage import gateway_class
from gateways.models import Gateway
from sensors.engine.availability import history
from sensors.engine.collection import COLLECTION_STOPPED, NOT_CHECKED, PRECEDENCE
from sensors.engine.replay import replay
from sensors.models import Sensor
from tests.conftest import at
from tests.helpers import device, register_gateway, register_sensor, set_coverage


def iso(day, hour=0, minute=0):
    return at(day, hour, minute).isoformat().replace("+00:00", "Z")


class TestExactStrings:
    """'The values in code are the exact strings the API returns.'"""

    def test_gateway_status(self):
        assert Gateway.Status.values == ["new", "spare", "connected", "stale", "disconnected", "suspended", "retired"]

    def test_gateway_command_state(self):
        assert Gateway.CommandState.values == [
            "running",
            "stop_pending",
            "stopped",
            "stop_failed",
            "resume_pending",
            "resume_failed",
        ]

    def test_coverage(self):
        pairs = itertools.product(Gateway.Status.values, Gateway.CommandState.values)
        classes = {gateway_class(s, c) for s, c in pairs}
        assert classes == {"available", "stopped", "recoverable", "dead"}

    def test_sensor_lifecycle(self):
        assert Sensor.Lifecycle.values == ["pending", "active", "dormant", "sampling", "retired", "decommissioned"]

    def test_sensor_collection(self):
        assert PRECEDENCE + [NOT_CHECKED, COLLECTION_STOPPED] == [
            "readings",
            "no_readings",
            "could_not_read",
            "timed_out",
            "not_checked",
            "collection_stopped",
        ]

    def test_batch_processing(self):
        assert set(Batch.Processing.values) == {
            "received",
            "processed",
            "partially_processed",
            "retrying",
            "quarantined",
        }


class TestGatewayCoverageClassTable:
    """Every status × command state, as in the brief's Coverage table."""

    @pytest.mark.parametrize(
        ("status", "command"), list(itertools.product(Gateway.Status.values, Gateway.CommandState.values))
    )
    def test_cell(self, status, command):
        if status == "connected":
            no_proof_stopped = command in ("running", "stop_pending", "stop_failed")
            expected = "available" if no_proof_stopped else "stopped"
        elif status in ("suspended", "retired"):
            expected = "dead"
        else:  # new, stale, disconnected (and spare: see DECISIONS.md)
            expected = "recoverable"
        assert gateway_class(status, command) == expected


def test_time_is_read_only_through_the_clock():
    """'Your code must read time only through this clock.' Only core/clock.py may read the wall clock."""
    root = Path(__file__).resolve().parents[1]
    wall_clock = re.compile(r"datetime\.now\(|datetime\.utcnow\(|timezone\.now\(|time\.time\(|date\.today\(")
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if not {".venv", "tests", "migrations"} & set(path.parts) and path.name != "clock.py"
        if wall_clock.search(path.read_text())
    ]
    assert offenders == []


@pytest.mark.django_db
class TestQualifyingEvidence:
    @pytest.fixture
    def g1(self, api, clock_at):
        clock_at(1, 12)
        token = register_gateway(api, "g1")
        register_sensor(api, "s1")
        set_coverage(api, "s1", ["g1"])
        return device(token)

    def test_a_partially_processed_batch_qualifies(self, g1, api):
        readings = [
            {"reading_id": "ok", "taken_at": iso(1, 11), "value": 1, "unit": "C"},
            {"reading_id": "bad", "taken_at": iso(1, 11), "value": 1, "unit": "mm"},
        ]
        g1.put("/gw/v1/batches/b1", {"sensor_id": "s1", "readings": readings}, format="json")
        api.post("/test/drain")
        assert api.get("/api/v1/batches/b1").json()["processing"] == "partially_processed"
        g = api.get("/api/v1/gateways/g1").json()
        assert (g["status"], g["last_qualifying_at"]) == ("connected", iso(1, 11))

    def test_a_batch_still_retrying_never_qualifies(self, g1, api):
        api.post("/test/faults", {"processing_failures": 1}, format="json")
        readings = [{"reading_id": "r1", "taken_at": iso(1, 11), "value": 1, "unit": "C"}]
        g1.put("/gw/v1/batches/b1", {"sensor_id": "s1", "readings": readings}, format="json")
        api.post("/test/drain")
        assert api.get("/api/v1/batches/b1").json()["processing"] == "retrying"
        assert api.get("/api/v1/gateways/g1").json()["status"] == "new"


@pytest.mark.django_db
class TestRequestOrder:
    """'First update the gateway, then recompute coverage, then apply the evidence to sensors.'"""

    def test_a_stale_gateways_first_good_cycle_counts_as_a_check(self, api, test_mode):
        def move(day, hour=0):
            api.post("/test/clock", {"now": iso(day, hour)}, format="json")

        def cycle(n, day, hour, outcome):
            result = {"sensor_id": "s1", "outcome": outcome} | ({"batch_id": "b0"} if outcome == "readings" else {})
            body = {
                "cycle_id": f"c{n}",
                "started_at": iso(day, hour),
                "finished_at": iso(day, hour),
                "session": "ok",
                "results": [result],
            }
            assert g.post("/gw/v1/cycles", body, format="json").status_code == 202

        move(0, 6)
        g = device(register_gateway(api, "g1"))
        register_sensor(api, "s1")
        set_coverage(api, "s1", ["g1"])
        cycle(1, 0, 6, "readings")
        readings = [{"reading_id": "r0", "taken_at": iso(0, 6), "value": 1, "unit": "C"}]
        g.put("/gw/v1/batches/b0", {"sensor_id": "s1", "readings": readings}, format="json")
        api.post("/test/drain")
        move(1, 9)  # 27h of silence: g1 went stale at day 0 18:00
        assert api.get("/api/v1/gateways/g1").json()["status"] == "stale"

        cycle(2, 1, 9, "no_readings")  # the stale gateway's first good cycle
        assert api.get("/api/v1/gateways/g1").json()["status"] == "connected"
        move(2)
        s = api.get("/api/v1/sensors/s1").json()
        # Day 1 counts as a quiet day: the cycle's gateway was available at its finished_at.
        assert (s["lifecycle"], s["quiet_checked_days"]) == ("active", 1)


@pytest.mark.django_db
def test_a_covering_gateway_leaving_suspended_makes_a_retired_sensor_pending(api, clock_at):
    """'A retired (no_live_coverage) sensor becomes pending as soon as its coverage is anything other than none.'"""
    clock_at(1, 8)
    g = device(register_gateway(api, "g1"))
    register_sensor(api, "s1")
    set_coverage(api, "s1", ["g1"])
    body = {
        "cycle_id": "c1",
        "started_at": iso(1, 8),
        "finished_at": iso(1, 8),
        "session": "ok",
        "results": [{"sensor_id": "s1", "outcome": "readings", "batch_id": "b1"}],
    }
    g.post("/gw/v1/cycles", body, format="json")
    readings = [{"reading_id": "r1", "taken_at": iso(1, 8), "value": 1, "unit": "C"}]
    g.put("/gw/v1/batches/b1", {"sensor_id": "s1", "readings": readings}, format="json")
    api.post("/test/drain")
    assert api.get("/api/v1/sensors/s1").json()["lifecycle"] == "active"

    clock_at(1, 9)
    api.post("/api/v1/gateways/g1/actions", {"action": "suspend", "reason": "x"}, format="json")
    s = api.get("/api/v1/sensors/s1").json()
    assert (s["lifecycle"], s["lifecycle_reason"]) == ("retired", "no_live_coverage")

    clock_at(1, 10)
    api.post("/api/v1/gateways/g1/actions", {"action": "unsuspend"}, format="json")
    s = api.get("/api/v1/sensors/s1").json()
    assert (s["lifecycle"], s["lifecycle_reason"], s["lifecycle_since"], s["coverage"]) == (
        "pending",
        None,
        iso(1, 10),
        "available",
    )
    lifecycle = [(e.to_value, e.rule) for e in timeline.entries("sensor", "s1") if e.axis == "lifecycle"]
    assert lifecycle[-2:] == [("retired", "no_live_coverage"), ("pending", "coverage_regained")]


def test_loss_of_coverage_comes_before_a_reading_at_the_same_instant():
    """'When several rules fire at the same instant: decommission, loss of coverage, readings, then timers.'"""
    from core.config import DEFAULT

    r = replay(
        created_at=at(0),
        now=at(2),
        coverage=history("available", at(0), [(at(1), "none")]),
        days=[],
        readings=[(at(0, 12), "r0"), (at(1), "r1")],
        no_readings=[],
        config_at=lambda t: DEFAULT,
    )
    # The coverage loss applies first; the reading at the same instant then finds coverage none.
    assert (r.lifecycle, r.reason, r.since) == ("retired", "no_live_coverage", at(1))


def cited_tests(text: str) -> list[str]:
    """Test ids cited in docs/conformance.md. `::test_x` reuses the previous id's file and class."""
    ids, last = [], None
    for ref in re.findall(r"`((?:test_\w+\.py)?::[\w:]+)`", text):
        if ref.startswith("::") and last:
            ref = last.rsplit("::", 1)[0] + ref
        ids.append(ref)
        last = ref
    return ids


def test_cited_tests_exist():
    """docs/conformance.md maps every brief rule to tests; each one it names must exist."""
    import importlib

    doc = Path(__file__).resolve().parents[2] / "docs" / "conformance.md"
    if not doc.is_file():
        pytest.skip("docs/ is not mounted here")
    ids = cited_tests(doc.read_text())
    assert len(ids) > 100
    missing = []
    for test_id in ids:
        file, *path = test_id.split("::")
        obj = importlib.import_module(f"tests.{file.removesuffix('.py')}")
        for name in path:
            obj = getattr(obj, name, None)
        if obj is None:
            missing.append(test_id)
    assert missing == []
