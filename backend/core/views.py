from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from core import dashboard
from core.openapi import CONSOLE_API, DashboardOut


def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


class DashboardView(APIView):
    """GET /api/v1/dashboard: situation counts for every axis."""

    @extend_schema(tags=[CONSOLE_API], summary="Situation counts for every axis", responses={200: DashboardOut})
    def get(self, request):
        return Response(dashboard.counts())
