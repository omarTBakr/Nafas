"""The scheduling service's activities: one side effect each, in the doctor's scope."""

import uuid
from datetime import UTC, datetime

from temporalio import activity

from nafas_core.db import session_scope
from nafas_scheduling.enums import NotificationKind
from nafas_scheduling.exceptions import AppointmentNotFoundError
from nafas_scheduling.logic import booking, notifications
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
            minutes_before=request.minutes_before,
        )


ACTIVITIES = [expire_hold, complete, notify]
