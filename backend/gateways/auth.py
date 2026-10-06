"""Bearer-token auth for the gateway API (/gw/v1/*).

The token identifies the gateway. Unknown token: 401. Retired gateway: 403,
and the request changes nothing.
"""

from core.errors import Forbidden, Unauthorized
from gateways.models import Gateway


def gateway_from_request(request, *, lock: bool = True) -> Gateway:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("unauthorized", "Missing or malformed bearer token.")
    qs = Gateway.objects.select_for_update() if lock else Gateway.objects
    gateway = qs.filter(token_hash=Gateway.hash_token(token.strip())).first()
    if gateway is None:
        raise Unauthorized("unauthorized", "Unknown gateway token.")
    if gateway.status == Gateway.Status.RETIRED:
        raise Forbidden("gateway_retired", f"Gateway {gateway.gateway_id} is retired.")
    return gateway
