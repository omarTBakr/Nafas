from fastapi.testclient import TestClient

from nafas_gateway.main import app


def test_health_is_open():
    """No dependency on it, so a monitor can reach it without a secret."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
