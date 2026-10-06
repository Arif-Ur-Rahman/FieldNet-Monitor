from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import openapi as doc
from core import timeline
from core.params import choices_filter
from sensors import services
from sensors.models import Sensor


class RegisterSensorIn(serializers.Serializer):
    sensor_id = serializers.RegexField(r"^[^/\s]+$", max_length=128)
    type = serializers.ChoiceField(choices=Sensor.Type.choices)


class CoverageIn(serializers.Serializer):
    gateway_ids = serializers.ListField(child=serializers.CharField(max_length=128), allow_empty=True)


class SensorActionIn(serializers.Serializer):
    action = serializers.ChoiceField(choices=["decommission"])
    reason = serializers.CharField(max_length=2000)


class SensorListView(APIView):
    @extend_schema(
        tags=[doc.CONSOLE_API],
        summary="List sensors",
        parameters=[
            OpenApiParameter("lifecycle", str, description="Comma-separated lifecycles, e.g. dormant,sampling.")
        ],
        responses={200: doc.SensorOut(many=True), **doc.errors(422)},
    )
    def get(self, request):
        """Every sensor's state, ordered by id. ?lifecycle=a,b filters by lifecycle."""
        sensors = Sensor.objects.order_by("sensor_id")
        lifecycles = choices_filter(request, "lifecycle", Sensor.Lifecycle.values)
        if lifecycles is not None:
            sensors = sensors.filter(lifecycle__in=lifecycles)
        return Response([services.serialize(s) for s in sensors])

    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Register a sensor (pending, no coverage)",
        request=RegisterSensorIn,
        responses={201: doc.SensorOut, **doc.errors(409, 422)},
    )
    def post(self, request):
        body = RegisterSensorIn(data=request.data)
        body.is_valid(raise_exception=True)
        sensor = services.register(body.validated_data["sensor_id"], body.validated_data["type"])
        return Response(services.serialize(sensor), status=status.HTTP_201_CREATED)


class SensorDetailView(APIView):
    @extend_schema(tags=[doc.OPERATOR_API], summary="Sensor state", responses={200: doc.SensorOut, **doc.errors(404)})
    def get(self, request, sensor_id):
        return Response(services.serialize(services.get(sensor_id)))


class SensorCoverageView(APIView):
    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Replace the gateways covering a sensor",
        request=CoverageIn,
        responses={200: doc.SensorOut, **doc.errors(404, 409, 422)},
    )
    def put(self, request, sensor_id):
        body = CoverageIn(data=request.data)
        body.is_valid(raise_exception=True)
        sensor = services.set_coverage(sensor_id, body.validated_data["gateway_ids"])
        return Response(services.serialize(sensor))


class SensorActionsView(APIView):
    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Operator action: decommission (terminal)",
        request=SensorActionIn,
        responses={200: doc.SensorOut, **doc.errors(404, 409, 422)},
    )
    def post(self, request, sensor_id):
        services.get(sensor_id)  # unknown sensor is 404 before body validation
        body = SensorActionIn(data=request.data)
        body.is_valid(raise_exception=True)
        sensor = services.decommission(sensor_id, body.validated_data["reason"])
        return Response(services.serialize(sensor))


class SensorTimelineView(APIView):
    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Sensor timeline, oldest first",
        responses={200: doc.TimelineEntryOut(many=True), **doc.errors(404)},
    )
    def get(self, request, sensor_id):
        services.get(sensor_id)
        return Response([timeline.serialize(e) for e in timeline.entries("sensor", sensor_id)])
