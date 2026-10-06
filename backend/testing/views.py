"""Test endpoints (/test/*). They exist only when TEST_MODE=1; otherwise every one is 404.

In TEST_MODE background work never runs on its own: it runs only inside
/test/clock and /test/drain, so every test is deterministic.
"""

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock
from core.errors import NotFound
from core.tick import tick
from core.timeutil import iso
from testing import faults

# Every table these apps own is emptied by /test/reset. Django's own tables are kept.
PROJECT_APPS = ["core", "gateways", "sensors", "batches", "testing"]


class TestModeView(APIView):
    def initial(self, request, *args, **kwargs):
        if not settings.TEST_MODE:
            raise NotFound("not_found", f"No route for {request.path}.")
        super().initial(request, *args, **kwargs)


def project_tables() -> list[str]:
    tables = set()
    for label in PROJECT_APPS:
        for model in apps.get_app_config(label).get_models():
            tables.add(model._meta.db_table)
            tables.update(f.remote_field.through._meta.db_table for f in model._meta.local_many_to_many)
    return sorted(tables)


class ResetView(TestModeView):
    def post(self, request):
        quoted = ", ".join(connection.ops.quote_name(t) for t in project_tables())
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClockIn(serializers.Serializer):
    now = serializers.DateTimeField()


class ClockView(TestModeView):
    def post(self, request):
        body = ClockIn(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            now = clock.set_now(body.validated_data["now"])
        tick(now)
        return Response({"now": iso(now)})


class DrainView(TestModeView):
    def post(self, request):
        now = clock.now()
        tick(now)
        return Response({"now": iso(now)})


class FaultsIn(serializers.Serializer):
    processing_failures = serializers.IntegerField(min_value=0)


class FaultsView(TestModeView):
    def post(self, request):
        body = FaultsIn(data=request.data)
        body.is_valid(raise_exception=True)
        faults.set_processing_failures(body.validated_data["processing_failures"])
        return Response(status=status.HTTP_204_NO_CONTENT)
