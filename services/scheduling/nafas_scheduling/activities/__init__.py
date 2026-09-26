"""The scheduling service's activities: one side effect each, in the doctor's scope."""

import uuid
from datetime import UTC, datetime

from temporalio import activity

from nafas_core.clients.identity import get_identity
from nafas_core.config import get_setting
from nafas_core.db import session_scope
from nafas_core.interfaces.email import get_email_sender
from nafas_scheduling.enums import NotificationKind
from nafas_scheduling.exceptions import AppointmentNotFoundError
from nafas_scheduling.logic import booking, emails, notifications
from nafas_scheduling.models import Appointment
from nafas_scheduling.schemas import AppointmentRef, NotificationRequest


@activity.defn(name="scheduling.expire_hold")
async def expire_hold(ref: AppointmentRef) -> bool:
    async with session_scope(doctor_id=uuid.UUID(ref.doctor_id)) as session:
        return await booking.expire_hold(session, uuid.UUID(ref.appointment_id), datetime.now(UTC))


@activity.defn(name="scheduling.complete")
async def complete(ref: AppointmentRef) -> bool:
    async with session_scope(doctor_id=uuid.UUID(ref.doctor_id)) as session:
        return await booking.complete(session, uuid.UUID(ref.appointment_id))


@activity.defn(name="scheduling.notify")
async def notify(request: NotificationRequest) -> None:
    async with session_scope(doctor_id=uuid.UUID(request.doctor_id)) as session:
        appointment = await session.get(Appointment, uuid.UUID(request.appointment_id))
        if appointment is None:
            raise AppointmentNotFoundError(request.appointment_id)
        await notifications.notify(
            session,
            notification_id=uuid.UUID(request.notification_id),
            appointment=appointment,
            kind=NotificationKind(request.kind),
            timezone=await booking.timezone_of(session, appointment.doctor_id),
            minutes_before=request.minutes_before,
        )


@activity.defn(name="scheduling.email_notice")
async def email_notice(request: NotificationRequest) -> str:
    """
    The notice by email too: "sent", "off" (no mail server configured), or
    "skipped" (no address, or the patient turned emails off). A retry after a
    send that went through can send twice; for a reminder that beats none.
    """
    async with session_scope(doctor_id=uuid.UUID(request.doctor_id)) as session:
        appointment = await session.get(Appointment, uuid.UUID(request.appointment_id))
        if appointment is None:
            raise AppointmentNotFoundError(request.appointment_id)
        timezone = await booking.timezone_of(session, appointment.doctor_id)

    identity = get_identity()
    profile = await identity.profile(appointment.patient_id)
    if not profile.get("email") or not profile.get("email_notices", True):
        return "skipped"
    doctor = await identity.doctor(appointment.doctor_id)
    language = profile["preferred_language"]

    email = emails.compose(
        kind=NotificationKind(request.kind),
        recipient=emails.Recipient(profile["email"], profile["full_name"], language),
        doctor_name=doctor["full_name_en"] if language == "en" else doctor["full_name_ar"],
        appointment_id=str(appointment.id),
        start=appointment.starts_at,
        end=appointment.ends_at,
        mode=appointment.mode.value,
        timezone=timezone,
        web_url=get_setting().web_url,
    )
    return "sent" if await get_email_sender().send(email) else "off"


ACTIVITIES = [expire_hold, complete, notify, email_notice]
