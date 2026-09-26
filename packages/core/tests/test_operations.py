"""What operations read: /metrics, /health, the startup check for staging and production, JSON logs."""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from nafas_core.config import Environment, Settings
from nafas_core.health import health_info
from nafas_core.logger import JsonFormatter
from nafas_core.metrics import count_llm, instrument
from nafas_core.startup import problems


def app() -> FastAPI:
    api = FastAPI()
    instrument(api, "test-svc")

    @api.get("/things/{thing_id}")
    async def thing(thing_id: str) -> dict:
        return {"id": thing_id}

    @api.get("/health")
    async def health() -> dict:
        return health_info("test-svc", prompts={"x": "x-v1"})

    return api


def test_requests_are_counted_by_route_template_never_by_path():
    client = TestClient(app())
    client.get("/things/0d079a98-36b5-41af-96c8-047a230807e8")
    client.get("/nowhere")

    text = client.get("/metrics").text

    assert 'nafas_http_requests_total{method="GET",route="/things/{thing_id}",service="test-svc",status="200"}' in text
    assert 'route="unmatched",service="test-svc",status="404"' in text
    assert "0d079a98" not in text
    # health checks and scrapes are not traffic
    assert 'route="/metrics"' not in text


def test_metrics_can_be_closed_behind_a_token(monkeypatch):
    import nafas_core.config

    monkeypatch.setenv("METRICS_TOKEN", "scrape-me")
    nafas_core.config._settings_instance = None
    client = TestClient(app())

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-me"}).status_code == 200


def test_model_calls_count_tokens_with_cache_as_input():
    class Usage:
        input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 10, 5, 100, 0

    count_llm("model-under-test", "ok", 0.3, Usage())
    text = TestClient(app()).get("/metrics").text

    assert 'nafas_llm_tokens_total{kind="input",model="model-under-test"} 110.0' in text
    assert 'nafas_llm_calls_total{model="model-under-test",outcome="ok"} 1.0' in text


def test_health_says_which_build_and_models_are_answering(monkeypatch):
    import nafas_core.config

    monkeypatch.setenv("GIT_SHA", "abc1234")
    nafas_core.config._settings_instance = None

    body = TestClient(app()).get("/health").json()

    assert body["status"] == "ok" and body["version"] == "abc1234" and body["environment"] == "dev"
    assert body["models"]["summary"] and body["prompts"] == {"x": "x-v1"}


def test_dev_may_run_on_laptop_defaults_and_production_may_not():
    assert problems(Settings(_env_file=None)) == []

    found = problems(Settings(_env_file=None, environment=Environment.PROD, forwarded_allow_ips="*", session_cookie_secure=False))

    assert any("INTERNAL_API_TOKEN" in p for p in found)
    assert any("JWT_SECRET" in p for p in found)
    assert any("DATABASE_URL" in p for p in found)
    assert any("FORWARDED_ALLOW_IPS" in p for p in found)
    assert any("SESSION_COOKIE_SECURE" in p for p in found)
    assert any("GIT_SHA" in p for p in found)


def test_production_with_real_settings_starts():
    ready = Settings(
        _env_file=None,
        environment=Environment.PROD,
        internal_api_token=SecretStr("i" * 40),
        jwt_secret=SecretStr("j" * 40),
        s3_secret_key=SecretStr("s" * 40),
        database_url="postgresql+asyncpg://nafas_identity_svc:long-secret@db:5432/nafas",
        forwarded_allow_ips="10.0.0.5",
        git_sha="abc1234",
    )

    assert problems(ready) == []
    traced = ready.model_copy(update={"langsmith_tracing": True})
    assert any("LangSmith" in p for p in problems(traced))
    hidden = traced.model_copy(update={"langsmith_hide_inputs": True, "langsmith_hide_outputs": True})
    assert problems(hidden) == []


@pytest.mark.parametrize("exc", [False, True])
def test_json_logs_are_one_object_per_line(exc):
    record = logging.LogRecord("nafas.test", logging.ERROR, __file__, 1, "booked %s", ("ok",), None)
    if exc:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()

    entry = json.loads(JsonFormatter().format(record))

    assert (entry["level"], entry["logger"], entry["message"]) == ("ERROR", "nafas.test", "booked ok")
    assert ("exception" in entry) is exc
