from datetime import UTC, datetime, timedelta

import pytest
from rest_framework import exceptions

from core import clock, config, timeline
from core.errors import Conflict, NotFound, exception_handler
from core.models import ConfigVersion, TimelineEntry
from core.timeutil import iso, parse_iso
from tests.conftest import at

pytestmark = pytest.mark.django_db


class TestClock:
    def test_wall_time_outside_test_mode(self, settings):
        settings.TEST_MODE = False
        before = datetime.now(UTC)
        assert before <= clock.now() <= datetime.now(UTC)

    def test_test_mode_uses_stored_clock(self, test_mode):
        clock.set_now(at(3))
        assert clock.now() == at(3)

    def test_moves_forward_and_same_time_is_allowed(self, test_mode):
        clock.set_now(at(1))
        clock.set_now(at(1))
        clock.set_now(at(2))
        assert clock.now() == at(2)

    def test_going_backwards_is_409(self, test_mode):
        clock.set_now(at(5))
        with pytest.raises(Conflict) as err:
            clock.set_now(at(4))
        assert err.value.status_code == 409
        assert clock.now() == at(5)


class TestTimeline:
    def test_seq_is_per_entity_and_starts_at_1(self, test_mode):
        clock.set_now(at(0))
        a1 = timeline.record_transition("gateway", "g1", "status", "new", "connected", rule="r", effective_at=at(0))
        a2 = timeline.record_transition("gateway", "g1", "status", "connected", "stale", rule="r", effective_at=at(1))
        b1 = timeline.record_transition("gateway", "g2", "status", "new", "connected", rule="r", effective_at=at(0))
        assert (a1.seq, a2.seq, b1.seq) == (1, 2, 1)

    def test_no_change_records_nothing(self, test_mode):
        assert (
            timeline.record_transition("sensor", "s1", "lifecycle", "active", "active", rule="r", effective_at=at(0))
            is None
        )
        assert not TimelineEntry.objects.exists()

    def test_recorded_at_comes_from_the_clock(self, test_mode):
        clock.set_now(at(10, 12))
        e = timeline.record_transition("sensor", "s1", "lifecycle", "pending", "active", rule="r", effective_at=at(2))
        assert e.recorded_at == at(10, 12)
        assert e.effective_at == at(2)

    def test_entries_are_append_only(self, test_mode):
        e = timeline.append("sensor", "s1", kind="action", rule="decommission", effective_at=at(0))
        e.rule = "edited"
        with pytest.raises(RuntimeError):
            e.save()
        with pytest.raises(RuntimeError):
            e.delete()

    def test_serialized_shape(self, test_mode):
        clock.set_now(at(1))
        e = timeline.record_transition(
            "gateway",
            "g1",
            "status",
            "new",
            "connected",
            rule="qualifying_evidence",
            effective_at=at(0, 12),
            evidence_ids=["cyc-1"],
        )
        assert timeline.serialize(e) == {
            "seq": 1,
            "kind": "transition",
            "axis": "status",
            "from": "new",
            "to": "connected",
            "effective_at": "2026-01-01T12:00:00Z",
            "recorded_at": "2026-01-02T00:00:00Z",
            "rule": "qualifying_evidence",
            "evidence_ids": ["cyc-1"],
            "detail": None,
        }


class TestConfig:
    def test_defaults_without_versions(self):
        c = config.config_at(at(0))
        assert c.quiet_days_before_dormant == 14
        assert c.dormant_wait == timedelta(days=14)
        assert c.sampling_window == timedelta(hours=72)
        assert c.sampling_cycles_before_retired == 2
        assert c.stale_after == timedelta(hours=12)
        assert c.command_timeout == timedelta(minutes=10)
        assert c.batch_deadline == timedelta(hours=24)

    def test_version_in_force_at_a_moment(self):
        ConfigVersion.objects.create(
            effective_from=at(10),
            recorded_at=at(10),
            quiet_days_before_dormant=7,
            dormant_wait_hours=24,
            sampling_window_hours=48,
            sampling_cycles_before_retired=3,
            stale_after_hours=6,
            command_timeout_minutes=5,
            batch_deadline_hours=12,
        )
        assert config.config_at(at(9)).quiet_days_before_dormant == 14
        assert config.config_at(at(10)).quiet_days_before_dormant == 7
        assert config.config_at(at(20)).stale_after == timedelta(hours=6)


class TestTimeutil:
    def test_iso_uses_z(self):
        assert iso(datetime(2026, 1, 1, 12, tzinfo=UTC)) == "2026-01-01T12:00:00Z"
        assert iso(None) is None

    def test_parse_iso(self):
        assert parse_iso("2026-01-01T12:00:00Z") == datetime(2026, 1, 1, 12, tzinfo=UTC)
        assert parse_iso("2026-01-01T14:00:00+02:00") == datetime(2026, 1, 1, 12, tzinfo=UTC)
        assert parse_iso("2026-01-01T12:00:00") == datetime(2026, 1, 1, 12, tzinfo=UTC)
        assert parse_iso("not a date") is None
        assert parse_iso(123) is None


class TestErrors:
    def test_validation_error_is_422_with_flat_detail(self):
        resp = exception_handler(exceptions.ValidationError({"sent_at": ["This field is required."]}), {})
        assert resp.status_code == 422
        assert resp.data == {"error": "invalid_body", "detail": "sent_at: This field is required."}

    def test_nested_validation_error(self):
        exc = exceptions.ValidationError({"results": [{"outcome": ["Bad value."]}]})
        assert exception_handler(exc, {}).data["detail"] == "results[0].outcome: Bad value."

    def test_bad_json_is_422(self):
        assert exception_handler(exceptions.ParseError("Malformed"), {}).status_code == 422

    def test_custom_codes(self):
        resp = exception_handler(Conflict("cycle_conflict", "Different body."), {})
        assert resp.status_code == 409
        assert resp.data == {"error": "cycle_conflict", "detail": "Different body."}
        assert exception_handler(NotFound(detail="No gateway g9."), {}).data["error"] == "not_found"

    def test_auth_errors(self):
        assert exception_handler(exceptions.AuthenticationFailed(), {}).status_code == 401
        assert exception_handler(exceptions.PermissionDenied(), {}).status_code == 403

    def test_unknown_route_is_json_404(self, client):
        resp = client.get("/no/such/route")
        assert resp.status_code == 404
        assert resp.json()["error"] == "not_found"
