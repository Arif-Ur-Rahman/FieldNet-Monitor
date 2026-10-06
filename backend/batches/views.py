from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from batches import services
from core import clock
from core.errors import Unprocessable
from gateways.auth import gateway_from_request


class BatchIn(serializers.Serializer):
    sensor_id = serializers.CharField(max_length=128)
    # Readings are checked one by one during processing, so an invalid reading
    # is quarantined with a reason instead of failing the whole request.
    readings = serializers.ListField(child=serializers.JSONField(), allow_empty=True)


class GatewayBatchView(APIView):
    """PUT /gw/v1/batches/{batch_id}: store the batch; tick() processes it in the background."""

    def put(self, request, batch_id):
        received_at = clock.now()
        with transaction.atomic():
            gateway = gateway_from_request(request)
            if len(batch_id) > 128:
                raise Unprocessable("invalid_body", "batch_id: at most 128 characters.")
            body = BatchIn(data=request.data)
            body.is_valid(raise_exception=True)
            data = body.validated_data
            batch, created = services.receive(gateway, batch_id, data, request.data, received_at=received_at)
        return Response(services.serialize(batch), status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


class BatchDetailView(APIView):
    """GET /api/v1/batches/{batch_id}: the batch's processing state."""

    def get(self, request, batch_id):
        return Response(services.serialize(services.get(batch_id)))
