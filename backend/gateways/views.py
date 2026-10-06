from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import timeline
from gateways import actions, services


class RegisterGatewayIn(serializers.Serializer):
    gateway_id = serializers.RegexField(r"^[^/\s]+$", max_length=128)
    name = serializers.CharField(max_length=200)


class GatewayActionIn(serializers.Serializer):
    action = serializers.ChoiceField(choices=actions.ACTIONS)
    reason = serializers.CharField(max_length=2000, required=False, allow_null=True, allow_blank=True)

    def validate(self, attrs):
        reason = (attrs.get("reason") or "").strip()
        if attrs["action"] == "suspend" and not reason:
            raise serializers.ValidationError({"reason": "Required to suspend."})
        attrs["reason"] = reason or None
        return attrs


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


class GatewayActionsView(APIView):
    def post(self, request, gateway_id):
        services.get(gateway_id)  # unknown gateway is 404 before body validation
        body = GatewayActionIn(data=request.data)
        body.is_valid(raise_exception=True)
        gateway = actions.perform(gateway_id, body.validated_data["action"], body.validated_data["reason"])
        return Response(services.serialize(gateway))
