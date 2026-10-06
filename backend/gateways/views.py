from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core import openapi as doc
from core import timeline
from core.params import choices_filter
from gateways import actions, services
from gateways.models import Gateway


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
    @extend_schema(
        tags=[doc.CONSOLE_API],
        summary="List gateways",
        parameters=[OpenApiParameter("status", str, description="Comma-separated statuses, e.g. stale,disconnected.")],
        responses={200: doc.GatewayOut(many=True), **doc.errors(422)},
    )
    def get(self, request):
        """Every gateway's state, ordered by id. ?status=a,b filters by status."""
        gateways = Gateway.objects.order_by("gateway_id")
        statuses = choices_filter(request, "status", Gateway.Status.values)
        if statuses is not None:
            gateways = gateways.filter(status__in=statuses)
        return Response([services.serialize(g) for g in gateways])

    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Register a gateway",
        request=RegisterGatewayIn,
        responses={201: doc.TokenOut, **doc.errors(409, 422)},
    )
    def post(self, request):
        body = RegisterGatewayIn(data=request.data)
        body.is_valid(raise_exception=True)
        token = services.register(**body.validated_data)
        return Response({"token": token}, status=status.HTTP_201_CREATED)


class GatewayDetailView(APIView):
    @extend_schema(tags=[doc.OPERATOR_API], summary="Gateway state", responses={200: doc.GatewayOut, **doc.errors(404)})
    def get(self, request, gateway_id):
        return Response(services.serialize(services.get(gateway_id)))


class GatewayTimelineView(APIView):
    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Gateway timeline, oldest first",
        responses={200: doc.TimelineEntryOut(many=True), **doc.errors(404)},
    )
    def get(self, request, gateway_id):
        services.get(gateway_id)
        return Response([timeline.serialize(e) for e in timeline.entries("gateway", gateway_id)])


class GatewayActionsView(APIView):
    @extend_schema(
        tags=[doc.OPERATOR_API],
        summary="Operator action: suspend, unsuspend, mark_spare, retire, stop, resume",
        request=GatewayActionIn,
        responses={200: doc.GatewayOut, **doc.errors(404, 409, 422)},
    )
    def post(self, request, gateway_id):
        services.get(gateway_id)  # unknown gateway is 404 before body validation
        body = GatewayActionIn(data=request.data)
        body.is_valid(raise_exception=True)
        gateway = actions.perform(gateway_id, body.validated_data["action"], body.validated_data["reason"])
        return Response(services.serialize(gateway))
