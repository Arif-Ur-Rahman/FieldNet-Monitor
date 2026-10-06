from django.db import connection
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from core import dashboard


def healthz(request):
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


class DashboardView(APIView):
    """GET /api/v1/dashboard: situation counts for every axis."""

    def get(self, request):
        return Response(dashboard.counts())
