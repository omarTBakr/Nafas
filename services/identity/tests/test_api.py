import httpx
import pytest

import nafas_core.config
from nafas_identity.api import app

from .conftest import PASSWORD

TOKEN = {"X-Internal-Token": "internal-secret"}


@pytest.fixture
async def client(monkeypatch):
    """The internal API in this test's event loop, so it shares the database pool."""
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    # settings may already be cached from before the token was set
    nafas_core.config._settings_instance = None

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://identity") as client:
        yield client


async def test_the_internal_api_refuses_calls_without_the_token(client):
    response = await client.post("/internal/v1/auth/verify", json={"email": "a@b.c", "password": "x"})

    assert response.status_code == 403


async def test_an_unset_token_refuses_everything(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    nafas_core.config._settings_instance = None

    response = await client.post(
        "/internal/v1/auth/verify", json={"email": "a@b.c", "password": "x"}, headers={"X-Internal-Token": ""}
    )

    assert response.status_code == 403


async def test_verify_returns_the_account(two_doctors, client):
    heart_id, _ = two_doctors

    ok = await client.post("/internal/v1/auth/verify", json={"email": "heart@example.com", "password": PASSWORD}, headers=TOKEN)
    wrong = await client.post(
        "/internal/v1/auth/verify", json={"email": "heart@example.com", "password": "nope nope nope"}, headers=TOKEN
    )

    assert ok.status_code == 200
    assert ok.json()["doctor_id"] == str(heart_id)
    assert wrong.status_code == 401
