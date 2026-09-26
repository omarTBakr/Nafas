import uuid

import httpx
import pytest

import nafas_core.config
from nafas_core.clients.identity import IdentityClient, set_identity
from nafas_gateway.main import app
from nafas_gateway.sessions import COOKIE_NAME

USER_ID = uuid.uuid4()
DOCTOR_ID = uuid.uuid4()
ACCOUNT = {"user_id": str(USER_ID), "email": "heart@example.com", "role": "doctor", "doctor_id": str(DOCTOR_ID)}


class FakeIdentity:
    """Stands in for the identity service's internal API."""

    def __init__(self):
        self.active = True
        self.token_ok = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.token_ok:
            return httpx.Response(403)
        if request.url.path == "/internal/v1/auth/verify":
            body = request.read()
            ok = b'"correct horse battery"' in body and self.active
            return httpx.Response(200, json=ACCOUNT) if ok else httpx.Response(401)
        if request.url.path == f"/internal/v1/users/{USER_ID}" and self.active:
            return httpx.Response(200, json=ACCOUNT)
        return httpx.Response(404)


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    nafas_core.config._settings_instance = None

    fake = FakeIdentity()
    set_identity(IdentityClient(httpx.AsyncClient(base_url="http://identity", transport=httpx.MockTransport(fake))))
    yield fake
    set_identity(None)


@pytest.fixture
async def client(identity):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
        yield client


async def login(client, password="correct horse battery"):
    return await client.post("/api/auth/login", json={"email": "heart@example.com", "password": password})


async def test_login_sets_an_httponly_session_and_me_reads_it(client):
    response = await login(client)

    assert response.status_code == 200
    assert response.json()["doctor_id"] == str(DOCTOR_ID)
    assert "httponly" in response.headers["set-cookie"].lower()

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "heart@example.com"


async def test_wrong_credentials_get_one_plain_answer(client):
    response = await login(client, password="wrong wrong wrong")

    assert response.status_code == 401
    assert COOKIE_NAME not in response.cookies


async def test_me_without_a_session_is_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_a_tampered_token_is_no_session(client):
    await login(client)
    token = client.cookies[COOKIE_NAME]
    client.cookies.set(COOKIE_NAME, token[:-2] + ("AA" if not token.endswith("AA") else "BB"))

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_disabling_the_account_ends_the_session_at_once(client, identity):
    await login(client)
    identity.active = False

    assert (await client.get("/api/auth/me")).status_code == 401


async def test_logout_clears_the_cookie(client):
    await login(client)
    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_a_misconfigured_internal_token_is_an_outage_not_a_bad_password(client, identity):
    identity.token_ok = False

    assert (await login(client)).status_code == 503


async def test_no_signing_secret_means_no_sessions(client, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "short")
    nafas_core.config._settings_instance = None

    assert (await login(client)).status_code == 500
