import logging

from fastapi.testclient import TestClient

from main import app


def test_health_is_open():
    """No dependency on it, so a monitor can reach it without a secret."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_does_not_reach_for_temporal(caplog):
    """
    With RUN_WORKER_IN_API off, the app must start with no Temporal server
    running — which is what makes this suite runnable anywhere.
    """
    with caplog.at_level(logging.INFO), TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert "worker not started in-process" in caplog.text
