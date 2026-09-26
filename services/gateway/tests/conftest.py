"""
The gateway wired in-process to the real services' apps, over the real
database with real row-level security. Only HTTP between the services is
short-circuited.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

import nafas_core.config
from nafas_conversation.api import app as conversation_app
from nafas_core.clients.conversation import ConversationClient, set_conversation
from nafas_core.clients.identity import IdentityClient, set_identity
from nafas_core.clients.scheduling import SchedulingClient, set_scheduling
from nafas_core.db import session_scope
from nafas_gateway.limits import limiter
from nafas_gateway.main import app as gateway
from nafas_identity.api import app as identity_app
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.seed import seed_specializations
from nafas_scheduling.api import app as scheduling_app
from nafas_scheduling.models import AvailabilityRule, BookingSettings

CAIRO = ZoneInfo("Africa/Cairo")
DOCTOR_PASSWORD = "doctor password 123"
PATIENT_PASSWORD = "patient password 123"


def next_wednesday(at: time) -> datetime:
    today = datetime.now(CAIRO).date()
    return datetime.combine(today + timedelta(days=(2 - today.weekday()) % 7 or 7), at, tzinfo=CAIRO)


@pytest.fixture
async def doctor_id(database, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    monkeypatch.setenv("JWT_SECRET", "s" * 40)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    nafas_core.config._settings_instance = None

    async with session_scope() as session:
        await seed_specializations(session)
        doctor = await create_doctor_account(
            session,
            email="heart@example.com",
            password=DOCTOR_PASSWORD,
            full_name_en="Dr Heart",
            full_name_ar="د. قلب",
            specialization_code="cardiology",
        )
    async with session_scope(doctor_id=doctor.id) as session:
        session.add(BookingSettings(doctor_id=doctor.id, timezone="Africa/Cairo"))
        session.add(AvailabilityRule(doctor_id=doctor.id, weekday=2, start_local=time(17), end_local=time(21)))

    set_identity(IdentityClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=identity_app), base_url="http://identity")))
    set_scheduling(
        SchedulingClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=scheduling_app), base_url="http://scheduling"))
    )
    set_conversation(
        ConversationClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=conversation_app), base_url="http://conversation"))
    )
    yield doctor.id
    set_identity(None)
    set_scheduling(None)
    set_conversation(None)


@pytest.fixture(autouse=True)
def fresh_limits():
    """Every test starts with empty rate-limit windows."""
    limiter.reset()
    yield
    limiter.reset()


def browser() -> httpx.AsyncClient:
    """One browser: its own cookie jar."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway), base_url="http://nafas")


async def sign_up(client, email="sara@example.com", name="سارة"):
    return await client.post(
        "/api/auth/register",
        json={"email": email, "password": PATIENT_PASSWORD, "full_name": name, "accept_data_processing": True},
    )


async def consent_to_chat(client, doctor_id):
    """What the chat panel's consent card does: agree to AI chat with this doctor."""
    response = await client.post("/api/me/consents", json={"kind": "ai_chat", "doctor_id": str(doctor_id)})
    assert response.status_code == 201
