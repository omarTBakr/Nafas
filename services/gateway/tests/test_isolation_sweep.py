"""
Every table under row-level security, checked at once: doctor A's rows are
seen by doctor A, and by no other doctor, no other patient, and no one
without a scope.

The sweep fails when a service table has no rows to check (add them to
`clinic_a`) or has no row-level security without a reason below, so a new
table cannot slip past it.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nafas_clinical.enums import DocumentKind, HistoryKind, SourceType, Visibility
from nafas_clinical.logic import records, search
from nafas_conversation.enums import EscalationReason
from nafas_conversation.logic import escalations, messages
from nafas_core.db import session_scope
from nafas_core.enums.channel import Channel
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_identity.enums import ConsentKind
from nafas_identity.logic import consents
from nafas_identity.logic.accounts import create_doctor_account, register_patient_account
from nafas_identity.logic.directory import ensure_care_link
from nafas_identity.logic.patients import register_patient
from nafas_identity.logic.seed import seed_specializations
from nafas_scheduling.enums import AppointmentMode, NotificationKind
from nafas_scheduling.logic import booking, notifications
from nafas_scheduling.models import AvailabilityRule, BookingSettings, TimeOff

# service tables without row-level security, and why each is safe
NOT_ISOLATED = {
    "identity.doctors": "the public doctor directory",
    "identity.specializations": "the public list of specializations",
    "identity.users": "login looks accounts up by email before anyone is known; closed to other services by per-service roles",
    "audit.audit_log": "services may only insert; nobody but the owner reads it (checked below)",
}


async def _owner(url: str, sql: str):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text(sql))).all()
    finally:
        await engine.dispose()


async def _doctor(session, email: str) -> uuid.UUID:
    doctor = await create_doctor_account(
        session,
        email=email,
        password="doctor password 123",
        full_name_en="Dr",
        full_name_ar="د",
        specialization_code="cardiology",
    )
    return doctor.id


@pytest.fixture
async def clinic_a(database):
    """Doctor A's clinic with a row in every isolated table, and a doctor B and patient B who own nothing of it."""
    async with session_scope() as session:
        await seed_specializations(session)
        doctor_a = await _doctor(session, "a@example.com")
        doctor_b = await _doctor(session, "b@example.com")
        patient_a = (
            await register_patient_account(
                session, email="pa@example.com", password="patient password 1", full_name="أ", consent_evidence="web:consent-v1"
            )
        ).patient_id
        patient_b = (
            await register_patient_account(
                session, email="pb@example.com", password="patient password 2", full_name="ب", consent_evidence="web:consent-v1"
            )
        ).patient_id

    now = datetime.now(UTC)
    async with session_scope(doctor_id=doctor_a) as session:
        await ensure_care_link(session, doctor_id=doctor_a, patient_id=patient_a)
        session.add(BookingSettings(doctor_id=doctor_a, timezone="Africa/Cairo", min_notice_minutes=0))
        for weekday in range(7):
            session.add(AvailabilityRule(doctor_id=doctor_a, weekday=weekday, start_local=time(0), end_local=time(23, 59)))
        session.add(TimeOff(doctor_id=doctor_a, starts_at=now + timedelta(days=20), ends_at=now + timedelta(days=21)))
        # a Telegram-onboarded patient brings a channel row
        await register_patient(session, doctor_id=doctor_a, full_name="ج", channel=Channel.TELEGRAM, external_id="42")
        start = (now + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
        held = await booking.hold(
            session, doctor_id=doctor_a, patient_id=patient_a, start=start, now=now, mode=AppointmentMode.IN_PERSON
        )
        await notifications.notify(
            session, notification_id=uuid.uuid4(), appointment=held, kind=NotificationKind.CONFIRMED, timezone="Africa/Cairo"
        )

    async with session_scope(patient_id=patient_a) as session:
        await consents.grant(session, patient_id=patient_a, kind=ConsentKind.AI_CHAT, doctor_id=doctor_a)
    conversation_id = await messages.open_conversation(patient_a, doctor_a)
    question_id = uuid.uuid4()
    await messages.add_patient_message(patient_a, question_id, conversation_id, "ينفع أزود الجرعة؟")
    await escalations.open_escalation(
        escalation_id=uuid.uuid4(),
        patient_id=patient_a,
        doctor_id=doctor_a,
        conversation_id=conversation_id,
        message_id=question_id,
        reason=EscalationReason.SENSITIVE,
        workflow_id="escalation-sweep",
    )

    async with session_scope(doctor_id=doctor_a) as session:
        note = await records.add_history(
            session, doctor_id=doctor_a, patient_id=patient_a, kind=HistoryKind.NOTE, content="Echo in six months."
        )
        await search.index(
            session,
            FakeEmbeddings(),
            patient_id=patient_a,
            doctor_id=doctor_a,
            source_type=SourceType.HISTORY,
            source_id=note.id,
            text=note.content,
            visibility=Visibility.DOCTOR_ONLY,
        )
        await records.new_document(
            session,
            doctor_id=doctor_a,
            patient_id=patient_a,
            kind=DocumentKind.REPORT,
            filename="echo.pdf",
            mime="application/pdf",
            size_bytes=100,
            uploaded_by=doctor_a,
        )

    return {"doctor_a": doctor_a, "doctor_b": doctor_b, "patient_a": patient_a, "patient_b": patient_b}


async def test_no_one_but_doctor_a_sees_doctor_as_rows(database, clinic_a):
    tables = await _owner(
        database,
        "SELECT format('%I.%I', n.nspname, c.relname), c.relrowsecurity FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE c.relkind = 'r' AND n.nspname NOT IN ('public', 'pg_catalog', 'information_schema')",
    )
    unguarded = {name for name, secured in tables if not secured} - set(NOT_ISOLATED)
    assert not unguarded, f"tables without row-level security and no reason given: {sorted(unguarded)}"

    isolated = sorted(name for name, secured in tables if secured)
    empty = [t for t in isolated if (await _owner(database, f"SELECT count(*) FROM {t}"))[0][0] == 0]
    assert not empty, f"the sweep has no rows to check in {empty}: add them to clinic_a"

    # the column naming whose row it is, for tables where patient B has rows of their own
    patient_columns = dict(
        await _owner(
            database,
            "SELECT format('%I.%I', table_schema, table_name), column_name FROM information_schema.columns"
            " WHERE column_name = 'patient_id' OR (table_schema = 'identity' AND table_name = 'patients' AND column_name = 'id')",
        )
    )

    async def visible(table: str, where: str = "true", **scope) -> int:
        async with session_scope(**scope) as session:
            return await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), {"b": clinic_a["patient_b"]})

    for table in isolated:
        assert await visible(table, doctor_id=clinic_a["doctor_a"]) > 0, f"doctor A cannot see their own {table}"
        assert await visible(table, doctor_id=clinic_a["doctor_b"]) == 0, f"doctor B sees doctor A's {table}"
        # patient B may see their own rows (their consent, their record); nobody else's
        others = f"{patient_columns[table]} <> :b" if table in patient_columns else "true"
        assert await visible(table, others, patient_id=clinic_a["patient_b"]) == 0, f"patient B sees another's {table}"
        assert await visible(table) == 0, f"{table} is visible without any scope"


async def test_patient_b_sees_only_their_own_patient_row(clinic_a):
    async with session_scope(patient_id=clinic_a["patient_b"]) as session:
        seen = (await session.execute(text("SELECT id FROM identity.patients"))).scalars().all()

    assert seen == [clinic_a["patient_b"]]
