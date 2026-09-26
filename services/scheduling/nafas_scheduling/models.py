"""The `scheduling` schema; every table is isolated per doctor by row-level security."""

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, SmallInteger, String, Text, Time, func, text
from sqlalchemy.dialects.postgresql import ENUM, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nafas_core.db import Base
from nafas_scheduling.enums import AppointmentMode, AppointmentStatus, AvailabilityMode

SCHEMA = "scheduling"


def _enum(enum_cls, name: str) -> ENUM:
    return ENUM(enum_cls, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e], create_type=False)


def _now() -> datetime:
    return datetime.now(UTC)


def _doctor_id(**kwargs) -> Mapped[uuid.UUID]:
    # the one kind of cross-service reference the plan allows (PLAN §4)
    return mapped_column(ForeignKey("identity.doctors.id"), **kwargs)


class BookingSettings(Base):
    """How a doctor takes bookings. No row: the doctor cannot be booked yet."""

    __tablename__ = "booking_settings"
    __table_args__ = (
        CheckConstraint("slot_minutes > 0", name="slot_positive"),
        CheckConstraint("buffer_minutes >= 0", name="buffer_not_negative"),
        CheckConstraint("min_notice_minutes >= 0", name="notice_not_negative"),
        CheckConstraint("horizon_days > 0", name="horizon_positive"),
        CheckConstraint("hold_minutes > 0", name="hold_positive"),
        {"schema": SCHEMA},
    )

    doctor_id: Mapped[uuid.UUID] = _doctor_id(primary_key=True)
    # IANA name; weekly hours and every "tomorrow at 5" are read in this zone
    timezone: Mapped[str] = mapped_column(String(64))
    slot_minutes: Mapped[int] = mapped_column(default=20, server_default=text("20"))
    buffer_minutes: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    min_notice_minutes: Mapped[int] = mapped_column(default=60, server_default=text("60"))
    horizon_days: Mapped[int] = mapped_column(default=60, server_default=text("60"))
    # how long a held slot waits for the patient's confirmation
    hold_minutes: Mapped[int] = mapped_column(default=10, server_default=text("10"))


class AvailabilityRule(Base):
    """One block of weekly hours: "Wednesdays 17:00-21:00, in person or online"."""

    __tablename__ = "availability_rules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_local > start_local", name="ends_after_start"),
        CheckConstraint("slot_minutes IS NULL OR slot_minutes > 0", name="slot_positive"),
        CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from", name="range_order"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = _doctor_id(index=True)
    # 0 = Monday, as Python's date.weekday()
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_local: Mapped[time] = mapped_column(Time)
    end_local: Mapped[time] = mapped_column(Time)
    mode: Mapped[AvailabilityMode] = mapped_column(
        _enum(AvailabilityMode, "availability_mode"), default=AvailabilityMode.BOTH, server_default="both"
    )
    slot_minutes: Mapped[int | None]
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class TimeOff(Base):
    __tablename__ = "time_off"
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ends_after_start"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = _doctor_id(index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        # "to the minute": no seconds, whoever writes the row
        CheckConstraint("starts_at = date_trunc('minute', starts_at)", name="whole_minute"),
        CheckConstraint("status <> 'held' OR hold_expires_at IS NOT NULL", name="held_expires"),
        # The guarantee: two held-or-confirmed appointments of one doctor can
        # never overlap, however concurrent requests race. [) ranges, so one
        # appointment may end exactly when the next begins.
        ExcludeConstraint(
            ("doctor_id", "="),
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=text("status IN ('held', 'confirmed')"),
            using="gist",
            name="no_overlapping_appointments",
        ),
        Index("ix_appointments_doctor_starts", "doctor_id", "starts_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = _doctor_id()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.patients.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(_enum(AppointmentStatus, "appointment_status"))
    mode: Mapped[AppointmentMode] = mapped_column(_enum(AppointmentMode, "appointment_mode"))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meeting_url: Mapped[str | None] = mapped_column(Text)
    reason_for_visit: Mapped[str | None] = mapped_column(Text)
    booking_workflow_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now())
