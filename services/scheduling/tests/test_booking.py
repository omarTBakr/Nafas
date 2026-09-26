import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from nafas_core.db import session_scope
from nafas_scheduling.enums import AppointmentMode, AppointmentStatus, Unavailable
from nafas_scheduling.exceptions import AppointmentNotFoundError, HoldExpiredError, SlotUnavailableError
from nafas_scheduling.logic import booking
from nafas_scheduling.models import Appointment

CAIRO = ZoneInfo("Africa/Cairo")
IN_PERSON = AppointmentMode.IN_PERSON
# a Monday morning; the clinic days are Wednesday 7th and Thursday 8th
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=CAIRO)
WED_1740 = datetime(2026, 10, 7, 17, 40, tzinfo=CAIRO)


async def _hold(clinic, start=WED_1740, patient=None, now=NOW):
    async with session_scope(doctor_id=clinic.doctor_id) as session:
        return await booking.hold(
            session, doctor_id=clinic.doctor_id, patient_id=patient or clinic.patient_id, start=start, now=now, mode=IN_PERSON
        )


async def test_hold_then_confirm_books_the_exact_minute(clinic):
    held = await _hold(clinic)

    assert held.status is AppointmentStatus.HELD
    assert held.starts_at == WED_1740 and held.ends_at == WED_1740 + timedelta(minutes=20)
    assert held.hold_expires_at == NOW + timedelta(minutes=10)

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        confirmed = await booking.confirm(session, held.id, NOW + timedelta(minutes=2))

    assert confirmed.status is AppointmentStatus.CONFIRMED
    assert confirmed.hold_expires_at is None


async def test_a_held_time_is_taken_for_everyone_else(clinic):
    await _hold(clinic)

    with pytest.raises(SlotUnavailableError) as refused:
        await _hold(clinic, start=WED_1740 + timedelta(minutes=10), patient=clinic.second_patient_id)

    assert refused.value.reason is Unavailable.TAKEN


async def test_two_requests_racing_for_one_minute_cannot_both_win(clinic):
    """
    The case the pure rules cannot catch: both requests check the schedule
    before either has written. The database's exclusion constraint decides:
    the second insert waits on the first transaction, then fails.
    """
    first_done = asyncio.Event()

    async def first():
        async with session_scope(doctor_id=clinic.doctor_id) as session:
            await booking.hold(
                session, doctor_id=clinic.doctor_id, patient_id=clinic.patient_id, start=WED_1740, now=NOW, mode=IN_PERSON
            )
            # still uncommitted: the second request cannot see this row yet
            await asyncio.sleep(0.3)
        first_done.set()

    async def second():
        await asyncio.sleep(0.1)
        async with session_scope(doctor_id=clinic.doctor_id) as session:
            await booking.hold(
                session,
                doctor_id=clinic.doctor_id,
                patient_id=clinic.second_patient_id,
                start=WED_1740,
                now=NOW,
                mode=IN_PERSON,
            )

    results = await asyncio.gather(first(), second(), return_exceptions=True)

    assert results[0] is None
    assert isinstance(results[1], SlotUnavailableError)
    assert results[1].reason is Unavailable.TAKEN

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        rows = (await session.scalars(select(Appointment))).all()
    assert [(a.patient_id, a.status) for a in rows] == [(clinic.patient_id, AppointmentStatus.HELD)]


async def test_a_lapsed_hold_frees_its_slot(clinic):
    abandoned = await _hold(clinic)
    later = NOW + timedelta(minutes=11)

    taken_over = await _hold(clinic, patient=clinic.second_patient_id, now=later)

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        assert (await session.get(Appointment, abandoned.id)).status is AppointmentStatus.CANCELLED
    assert taken_over.status is AppointmentStatus.HELD


async def test_a_lapsed_hold_cannot_be_confirmed(clinic):
    held = await _hold(clinic)

    with pytest.raises(HoldExpiredError):
        async with session_scope(doctor_id=clinic.doctor_id) as session:
            await booking.confirm(session, held.id, NOW + timedelta(minutes=10))


async def test_refusals_carry_the_reason(clinic):
    with pytest.raises(SlotUnavailableError) as refused:
        await _hold(clinic, start=datetime(2026, 10, 7, 21, 0, tzinfo=CAIRO))

    assert refused.value.reason is Unavailable.OUTSIDE_HOURS


async def test_a_doctor_without_hours_cannot_be_booked(clinic):
    with pytest.raises(SlotUnavailableError) as refused:
        async with session_scope(doctor_id=clinic.other_doctor_id) as session:
            await booking.find_available(session, clinic.other_doctor_id, NOW, NOW + timedelta(days=7), NOW, IN_PERSON)

    assert refused.value.reason is Unavailable.NOT_BOOKABLE


async def test_another_doctor_cannot_see_or_touch_the_appointment(clinic):
    held = await _hold(clinic)

    with pytest.raises(AppointmentNotFoundError):
        async with session_scope(doctor_id=clinic.other_doctor_id) as session:
            await booking.cancel(session, held.id)


async def test_find_and_suggest_come_from_the_real_schedule(clinic):
    await _hold(clinic, start=datetime(2026, 10, 7, 18, 0, tzinfo=CAIRO))

    async with session_scope(doctor_id=clinic.doctor_id) as session:
        wednesday = await booking.find_available(
            session, clinic.doctor_id, datetime(2026, 10, 7, tzinfo=CAIRO), datetime(2026, 10, 8, tzinfo=CAIRO), NOW, IN_PERSON
        )
        near = await booking.suggest(session, clinic.doctor_id, datetime(2026, 10, 7, 18, 0, tzinfo=CAIRO), NOW, IN_PERSON)

    assert "18:00" not in [s.start.astimezone(CAIRO).strftime("%H:%M") for s in wednesday]
    assert [s.start.astimezone(CAIRO).strftime("%H:%M") for s in near] == ["17:20", "17:40", "18:20"]


async def test_the_database_refuses_seconds_whoever_writes(clinic, database):
    """The whole-minute rule holds even for a writer that skips the service's checks."""
    from sqlalchemy.ext.asyncio import create_async_engine

    owner = create_async_engine(database)
    try:
        with pytest.raises(IntegrityError, match="whole_minute"):
            async with owner.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO scheduling.appointments (id, doctor_id, patient_id, starts_at, ends_at, status, mode)"
                        " VALUES (gen_random_uuid(), :doctor, :patient, '2026-10-07 17:40:30+03', '2026-10-07 18:00+03',"
                        " 'confirmed', 'in_person')"
                    ),
                    {"doctor": clinic.doctor_id, "patient": clinic.patient_id},
                )
    finally:
        await owner.dispose()
