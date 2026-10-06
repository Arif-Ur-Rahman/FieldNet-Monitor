from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core import config, dashboard, rule_changes
from core.errors import Unprocessable
from core.openapi import CONSOLE_API, OPERATOR_API, ConfigOut, DashboardOut, errors
from core.timeutil import iso


def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


class DashboardView(APIView):
    """GET /api/v1/dashboard: situation counts for every axis."""

    @extend_schema(tags=[CONSOLE_API], summary="Situation counts for every axis", responses={200: DashboardOut})
    def get(self, request):
        return Response(dashboard.counts())


class ConfigIn(serializers.Serializer):
    """Any subset of the thresholds; the others keep their current value."""

    quiet_days_before_dormant = serializers.IntegerField(min_value=1, required=False)
    dormant_wait_hours = serializers.IntegerField(min_value=1, required=False)
    sampling_window_hours = serializers.IntegerField(min_value=1, required=False)
    sampling_cycles_before_retired = serializers.IntegerField(min_value=1, required=False)
    stale_after_hours = serializers.IntegerField(min_value=1, required=False)
    command_timeout_minutes = serializers.IntegerField(min_value=1, required=False)
    batch_deadline_hours = serializers.IntegerField(min_value=1, required=False)


def config_out(values: dict) -> dict:
    return values | {"effective_from": iso(values["effective_from"])}


class ConfigView(APIView):
    @extend_schema(tags=[OPERATOR_API], summary="Thresholds in force", responses={200: ConfigOut})
    def get(self, request):
        return Response(config_out(rule_changes.current()))

    @extend_schema(
        tags=[OPERATOR_API],
        summary="Change thresholds (effective now; writes rule_change entries)",
        request=ConfigIn,
        responses={200: ConfigOut, **errors(422)},
    )
    def put(self, request):
        unknown = sorted(set(request.data) - set(config.FIELDS)) if isinstance(request.data, dict) else []
        if unknown:
            raise Unprocessable("invalid_body", f"Unknown threshold {unknown[0]!r}; one of {', '.join(config.FIELDS)}.")
        body = ConfigIn(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(config_out(rule_changes.apply(body.validated_data)))
