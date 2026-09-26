"""The `consultation` schema: one row per recorded visit. The doctor's own; row-level security reads doctor_id."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nafas_consultation.enums import ConsultationStatus
from nafas_core.db import Base

SCHEMA = "consultation"


def _now() -> datetime:
    return datetime.now(UTC)


class Consultation(Base):
    """
    A recorded in-person visit. Audio lives in storage as numbered parts; the
    transcript, the model's draft and the doctor's approved version live here.
    What reaches the patient's record is written to clinical-records on approval.
    """

    __tablename__ = "consultations"
    __table_args__ = (
        Index("ix_consultations_doctor_patient_created", "doctor_id", "patient_id", "created_at"),
        Index("ix_consultations_room", "room"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # the identity consent row recorded for this recording, and no other
    consent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[ConsultationStatus] = mapped_column(
        ENUM(
            ConsultationStatus,
            name="consultation_status",
            schema=SCHEMA,
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        default=ConsultationStatus.RECORDING,
        server_default="recording",
    )
    # "in_person" (the browser recorder) or "online" (a LiveKit room)
    source: Mapped[str] = mapped_column(String(16), default="in_person", server_default="in_person")
    room: Mapped[str | None] = mapped_column(String(100))
    # online: when the doctor stopped; the visit is processed once every track's file is written
    recording_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # [{"index", "mime", "offset_seconds", "key"}], in the order recorded; online parts add
    # "speaker" (doctor or patient), "egress_id" and "state" (recording, written, failed)
    parts: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # [{"start", "end", "text"}], in seconds from the start of the recording
    transcript: Mapped[list | None] = mapped_column(JSONB)
    draft: Mapped[dict | None] = mapped_column(JSONB)
    approved: Mapped[dict | None] = mapped_column(JSONB)
    share_with_patient: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
