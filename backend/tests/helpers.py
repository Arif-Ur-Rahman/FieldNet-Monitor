"""Shared API helpers for tests."""

from rest_framework.test import APIClient


def register_gateway(api, gid="g1", name="Gateway 1"):
    resp = api.post("/api/v1/gateways", {"gateway_id": gid, "name": name}, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["token"]


def register_sensor(api, sid="s1", type_="temperature"):
    resp = api.post("/api/v1/sensors", {"sensor_id": sid, "type": type_}, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()


def set_coverage(api, sid, gateway_ids):
    return api.put(f"/api/v1/sensors/{sid}/coverage", {"gateway_ids": gateway_ids}, format="json")


def device(token) -> APIClient:
    """A client that calls the gateway API as the gateway owning `token`."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client
