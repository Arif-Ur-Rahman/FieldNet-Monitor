from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import timeline
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
    def post(self, request):
        body = RegisterSensorIn(data=request.data)
        body.is_valid(raise_exception=True)
        sensor = services.register(body.validated_data["sensor_id"], body.validated_data["type"])
        return Response(services.serialize(sensor), status=status.HTTP_201_CREATED)


class SensorDetailView(APIView):
    def get(self, request, sensor_id):
        return Response(services.serialize(services.get(sensor_id)))


class SensorCoverageView(APIView):
    def put(self, request, sensor_id):
        body = CoverageIn(data=request.data)
        body.is_valid(raise_exception=True)
        sensor = services.set_coverage(sensor_id, body.validated_data["gateway_ids"])
        return Response(services.serialize(sensor))


class SensorActionsView(APIView):
    def post(self, request, sensor_id):
        services.get(sensor_id)  # unknown sensor is 404 before body validation
        body = SensorActionIn(data=request.data)
        body.is_valid(raise_exception=True)
        sensor = services.decommission(sensor_id, body.validated_data["reason"])
        return Response(services.serialize(sensor))


class SensorTimelineView(APIView):
    def get(self, request, sensor_id):
        services.get(sensor_id)
        return Response([timeline.serialize(e) for e in timeline.entries("sensor", sensor_id)])
