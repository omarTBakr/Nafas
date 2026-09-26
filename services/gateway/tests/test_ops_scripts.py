"""The load test and the release check, run for real against a gateway served over HTTP."""

import asyncio
import socket
from datetime import time

import pytest
import uvicorn
from sqlalchemy import update

from nafas_core.db import session_scope
from nafas_gateway.main import app as gateway
from nafas_scheduling.models import AvailabilityRule, BookingSettings
from scripts import load_test, release_check


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def served(doctor_id, monkeypatch):
    """The gateway on a real port, the services behind it in-process, trusting the load test's forwarded addresses."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    async with session_scope(doctor_id=doctor_id) as session:
        await session.execute(update(BookingSettings).where(BookingSettings.doctor_id == doctor_id).values(min_notice_minutes=0))
        for weekday in range(7):
            session.add(AvailabilityRule(doctor_id=doctor_id, weekday=weekday, start_local=time(8), end_local=time(20)))
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(gateway, host="127.0.0.1", port=port, log_level="warning", forwarded_allow_ips="127.0.0.1")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def test_the_load_test_runs_patients_through_the_gateway_and_judges_the_run(served):
    summary, passed = await load_test.run(served, users=4, seconds=3, chat=False)

    routes = summary["routes"]
    assert routes["POST /api/auth/register"]["requests"] == 4 and routes["POST /api/auth/register"]["errors"] == 0
    for route in ("GET /api/doctors", "GET /api/doctors/{id}/slots", "GET /api/appointments/mine", "GET /api/notifications"):
        assert routes[route]["requests"] >= 4 and routes[route]["errors"] == 0, route
    assert summary["error_rate"] == 0.0 and passed is (all(r["met"] for r in routes.values()))


async def test_the_release_check_passes_the_build_that_is_running_and_stops_any_other(served):
    ok = await release_check.check([served], expect="unversioned", environment="dev")
    wrong = await release_check.check([served], expect="abc1234", environment="dev")
    gone = await release_check.check(["http://127.0.0.1:1"], expect="unversioned", environment="dev")

    assert ok == {served: None}
    assert "not 'abc1234'" in wrong[served]
    assert gone["http://127.0.0.1:1"] == "did not answer /health"
