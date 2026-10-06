"""The gateway API (/gw/v1/*), called by devices with a bearer token."""

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import clock
from gateways import ingest
from gateways.auth import gateway_from_request
from gateways.models import Session


class HeartbeatIn(serializers.Serializer):
    sent_at = serializers.DateTimeField()
    session = serializers.ChoiceField(choices=Session.choices)


class CycleResultIn(serializers.Serializer):
    sensor_id = serializers.CharField(max_length=128)
    outcome = serializers.ChoiceField(choices=list(ingest.REPORTED_TO_RECORDED))
    batch_id = serializers.CharField(max_length=128, required=False, allow_null=True)

    def validate(self, attrs):
        has_batch = attrs.get("batch_id") is not None
        if attrs["outcome"] == "readings" and not has_batch:
            raise serializers.ValidationError({"batch_id": "Required when outcome is readings."})
        if attrs["outcome"] != "readings" and has_batch:
            raise serializers.ValidationError({"batch_id": "Must be absent unless outcome is readings."})
        return attrs


class CycleIn(serializers.Serializer):
    cycle_id = serializers.CharField(max_length=128)
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField()
    session = serializers.ChoiceField(choices=Session.choices)
    results = CycleResultIn(many=True, allow_empty=True)

    def validate(self, attrs):
        if attrs["started_at"] > attrs["finished_at"]:
            raise serializers.ValidationError({"finished_at": "Must not be before started_at."})
        ids = [r["sensor_id"] for r in attrs["results"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({"results": "Each sensor may appear once per cycle."})
        return attrs


class HeartbeatView(APIView):
    def post(self, request):
        received_at = clock.now()
        with transaction.atomic():
            gateway = gateway_from_request(request)
            body = HeartbeatIn(data=request.data)
            body.is_valid(raise_exception=True)
            ingest.record_heartbeat(gateway, received_at=received_at, **body.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CycleView(APIView):
    def post(self, request):
        received_at = clock.now()
        with transaction.atomic():
            gateway = gateway_from_request(request)
            body = CycleIn(data=request.data)
            body.is_valid(raise_exception=True)
            cycle, created = ingest.record_cycle(gateway, body.validated_data, request.data, received_at=received_at)
        return Response({"ignored": cycle.ignored}, status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)
