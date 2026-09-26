"""In-app notifications: written in the doctor's scope, read and dismissed in the patient's."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_scheduling.enums import NotificationKind
from nafas_scheduling.models import Appointment, Notification


async def notify(
    session: AsyncSession,
    *,
    notification_id: uuid.UUID,
    appointment: Appointment,
    kind: NotificationKind,
    timezone: str,
    minutes_before: int | None = None,
) -> None:
    """One notice about `appointment` to its patient; the same id twice (a retry) stores it once."""
    await session.execute(
        insert(Notification)
        .values(
            id=notification_id,
            doctor_id=appointment.doctor_id,
            patient_id=appointment.patient_id,
            appointment_id=appointment.id,
            kind=kind,
            minutes_before=minutes_before,
            details={"start": appointment.starts_at.isoformat(), "mode": appointment.mode.value, "timezone": timezone},
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )


async def patient_notifications(session: AsyncSession, *, unread_only: bool, limit: int) -> list[Notification]:
    """The current patient's notices, newest first (patient scope: the policy picks the rows)."""
    query = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return list((await session.scalars(query)).all())


async def mark_read(session: AsyncSession, notification_id: uuid.UUID, now: datetime) -> bool:
    """False when there is no such notice for this patient."""
    result = await session.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(read_at=now)
        .returning(Notification.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None
