"""Response shapes for the OpenAPI schema (/api/schema/, /api/docs/).

These serializers only describe what the views return; the views build their
responses with each app's serialize(). Error responses share one shape.
"""

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers

from batches.models import Batch
from core.dashboard import COLLECTION, RETIRED_REASONS, SENSOR_COVERAGE
from core.models import TimelineEntry
from gateways.coverage import AVAILABLE, DEAD, RECOVERABLE, STOPPED
from gateways.models import Command, Gateway
from sensors.models import Sensor

GATEWAY_API = "Gateway API (devices, bearer token)"
OPERATOR_API = "Operator and state API"
CONSOLE_API = "Console API"
TEST_API = "Test endpoints (TEST_MODE=1 only)"

# The gateway API's bearer token, declared in SPECTACULAR_SETTINGS.
GATEWAY_AUTH = [{"gatewayToken": []}]


class ErrorOut(serializers.Serializer):
    error = serializers.CharField(help_text="Machine-readable code, e.g. invalid_body, cycle_conflict.")
    detail = serializers.CharField()


def errors(*codes: int) -> dict:
    meaning = {
        401: "Unknown or missing gateway token.",
        403: "The gateway is retired; the request changed nothing.",
        404: "Unknown gateway, sensor, batch or command.",
        409: "Conflict or illegal action.",
        422: "Invalid body or parameter.",
    }
    return {code: OpenApiResponse(ErrorOut, description=meaning[code]) for code in codes}


class TokenOut(serializers.Serializer):
    token = serializers.CharField(help_text="The gateway's bearer token. Shown once; only a hash is stored.")


class GatewayOut(serializers.Serializer):
    gateway_id = serializers.CharField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=Gateway.Status.values)
    status_since = serializers.DateTimeField()
    command_state = serializers.ChoiceField(choices=Gateway.CommandState.values)
    coverage_class = serializers.ChoiceField(choices=[AVAILABLE, STOPPED, RECOVERABLE, DEAD])
    last_heartbeat_at = serializers.DateTimeField(allow_null=True, help_text="Received time of the latest heartbeat.")
    last_qualifying_at = serializers.DateTimeField(
        allow_null=True, help_text="Event time of the newest qualifying evidence."
    )
    disconnected_since = serializers.DateTimeField(allow_null=True)
    flags = serializers.ListField(child=serializers.ChoiceField(choices=["collecting_after_stop"]))


class SensorOut(serializers.Serializer):
    sensor_id = serializers.CharField()
    type = serializers.ChoiceField(choices=Sensor.Type.values)
    lifecycle = serializers.ChoiceField(choices=Sensor.Lifecycle.values)
    lifecycle_reason = serializers.CharField(
        allow_null=True,
        help_text="no_readings or no_live_coverage when retired; the operator's text when decommissioned.",
    )
    lifecycle_since = serializers.DateTimeField()
    collection = serializers.ChoiceField(choices=COLLECTION)
    coverage = serializers.ChoiceField(choices=SENSOR_COVERAGE)
    quiet_checked_days = serializers.IntegerField()
    sampling_cycles_done = serializers.IntegerField()
    next_evaluation_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the current wait or window ends if coverage stays available; null while paused.",
    )


# Built with type() because one field is called "from", a Python keyword.
TimelineEntryOut = type(
    "TimelineEntryOut",
    (serializers.Serializer,),
    {
        "seq": serializers.IntegerField(),
        "kind": serializers.ChoiceField(choices=TimelineEntry.Kind.values),
        "axis": serializers.CharField(allow_null=True),
        "from": serializers.CharField(allow_null=True),
        "to": serializers.CharField(allow_null=True),
        "effective_at": serializers.DateTimeField(),
        "recorded_at": serializers.DateTimeField(),
        "rule": serializers.CharField(),
        "evidence_ids": serializers.ListField(child=serializers.CharField()),
        "detail": serializers.JSONField(
            allow_null=True,
            help_text="A correction's recomputed transitions, an action's reason, a flag's stop period.",
        ),
    },
)


class QuarantinedOut(serializers.Serializer):
    reading_id = serializers.CharField(allow_null=True)
    reason = serializers.CharField()


class BatchOut(serializers.Serializer):
    processing = serializers.ChoiceField(choices=Batch.Processing.values)
    attempts = serializers.IntegerField()
    accepted_count = serializers.IntegerField()
    quarantined = QuarantinedOut(many=True)


class CommandOut(serializers.Serializer):
    command_id = serializers.CharField()
    seq = serializers.IntegerField()
    type = serializers.ChoiceField(choices=Command.Type.values)
    issued_at = serializers.DateTimeField()


class CommandsOut(serializers.Serializer):
    commands = CommandOut(many=True, help_text="At most one: the latest command, while unacknowledged.")


class IgnoredOut(serializers.Serializer):
    ignored = serializers.ListField(child=serializers.CharField(), help_text="Sensors this gateway does not cover.")


class NowOut(serializers.Serializer):
    now = serializers.DateTimeField()


def counts(values, help_text: str = "") -> serializers.DictField:
    return serializers.DictField(
        child=serializers.IntegerField(), help_text=help_text or f"One key per value: {', '.join(values)}."
    )


class GatewayCountsOut(serializers.Serializer):
    total = serializers.IntegerField()
    status = counts(Gateway.Status.values)
    command_state = counts(Gateway.CommandState.values)
    coverage_class = counts([AVAILABLE, STOPPED, RECOVERABLE, DEAD])
    flags = counts(["collecting_after_stop"])


class SensorCountsOut(serializers.Serializer):
    total = serializers.IntegerField()
    lifecycle = counts(Sensor.Lifecycle.values)
    retired_reason = counts(RETIRED_REASONS)
    coverage = counts(SENSOR_COVERAGE)
    collection = counts(COLLECTION)


class BatchCountsOut(serializers.Serializer):
    total = serializers.IntegerField()
    processing = counts(Batch.Processing.values)


class ConfigOut(serializers.Serializer):
    effective_from = serializers.DateTimeField(
        allow_null=True, help_text="When this version took effect; null for the defaults."
    )
    quiet_days_before_dormant = serializers.IntegerField()
    dormant_wait_hours = serializers.IntegerField(help_text="Of available time.")
    sampling_window_hours = serializers.IntegerField(help_text="Of available time.")
    sampling_cycles_before_retired = serializers.IntegerField()
    stale_after_hours = serializers.IntegerField()
    command_timeout_minutes = serializers.IntegerField()
    batch_deadline_hours = serializers.IntegerField()


class DashboardOut(serializers.Serializer):
    gateways = GatewayCountsOut()
    sensors = SensorCountsOut()
    batches = BatchCountsOut()
