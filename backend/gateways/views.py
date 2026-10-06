from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import timeline
from gateways import services


class RegisterGatewayIn(serializers.Serializer):
    gateway_id = serializers.RegexField(r"^[^/\s]+$", max_length=128)
    name = serializers.CharField(max_length=200)


class GatewayListView(APIView):
    def post(self, request):
        body = RegisterGatewayIn(data=request.data)
        body.is_valid(raise_exception=True)
        token = services.register(**body.validated_data)
        return Response({"token": token}, status=status.HTTP_201_CREATED)


class GatewayDetailView(APIView):
    def get(self, request, gateway_id):
        return Response(services.serialize(services.get(gateway_id)))


class GatewayTimelineView(APIView):
    def get(self, request, gateway_id):
        services.get(gateway_id)
        return Response([timeline.serialize(e) for e in timeline.entries("gateway", gateway_id)])
