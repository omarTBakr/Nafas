"""
Prometheus metrics: what every service exposes on /metrics, and the
behavioural counters the dashboards and alerts read (docs/operations/slo.md).

System metrics come from `instrument`, per request, labelled by the route's
template (never the raw path, which carries ids). Behavioural ones are
counted where the thing happens: a model call, a gate's verdict, an
escalation, a booking, a visit note. No label ever carries patient data.
"""

import secrets
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from nafas_core.config import get_setting

REQUESTS = Counter("nafas_http_requests_total", "HTTP requests served", ["service", "method", "route", "status"])
REQUEST_SECONDS = Histogram(
    "nafas_http_request_seconds",
    "Time to the response's first byte",
    ["service", "method", "route"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

LLM_CALLS = Counter("nafas_llm_calls_total", "Model calls, by how they ended", ["model", "outcome"])
LLM_SECONDS = Histogram("nafas_llm_call_seconds", "Model call time", ["model"], buckets=(0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 120))
LLM_TOKENS = Counter("nafas_llm_tokens_total", "Tokens in and out, cache reads and writes counted as input", ["model", "kind"])

GATE_VERDICTS = Counter(
    "nafas_safety_gate_verdicts_total", "Each safety gate's verdicts on patient messages", ["gate", "verdict"]
)
ESCALATIONS = Counter("nafas_escalations_total", "Questions sent to the doctor instead of answered", ["reason"])
BOOKINGS = Counter("nafas_booking_events_total", "Appointments held, confirmed, cancelled, expired, missed", ["event"])
VISIT_NOTES = Counter(
    "nafas_visit_notes_total", "Recorded visits by outcome: approved as drafted or edited, discarded, failed", ["outcome"]
)
REPLY_FEEDBACK = Counter("nafas_reply_feedback_total", "Patients' thumbs on the assistant's replies", ["rating"])
WORKFLOW_FAILURES = Counter("nafas_workflow_failures_total", "Workflows that ended in a failure state", ["workflow"])


class _Measure:
    """Pure ASGI, so streamed responses (the doctor assistant's SSE) pass straight through."""

    def __init__(self, app, service: str):
        self.app, self.service = app, service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in ("/metrics", "/health"):
            return await self.app(scope, receive, send)
        start, status = perf_counter(), {"code": 500}

        async def recording_send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                REQUEST_SECONDS.labels(self.service, scope["method"], _route(scope)).observe(perf_counter() - start)
            await send(message)

        try:
            await self.app(scope, receive, recording_send)
        finally:
            REQUESTS.labels(self.service, scope["method"], _route(scope), str(status["code"])).inc()


def _route(scope) -> str:
    route = scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def instrument(app: FastAPI, service: str) -> None:
    """Request metrics on every route, and GET /metrics (behind METRICS_TOKEN when it is set)."""
    app.add_middleware(_Measure, service=service)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        token = get_setting().metrics_token.get_secret_value()
        given = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token and not secrets.compare_digest(given, token):
            return PlainTextResponse("metrics need the metrics token", status_code=401)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def count_llm(model: str | None, outcome: str, seconds: float, usage=None) -> None:
    model = model or "unknown"
    LLM_CALLS.labels(model, outcome).inc()
    LLM_SECONDS.labels(model).observe(seconds)
    if usage is not None:
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        LLM_TOKENS.labels(model, "input").inc((usage.input_tokens or 0) + read + written)
        LLM_TOKENS.labels(model, "output").inc(usage.output_tokens or 0)
