import pytest


@pytest.mark.django_db
def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_schema_renders(client):
    resp = client.get("/api/schema/")
    assert resp.status_code == 200
