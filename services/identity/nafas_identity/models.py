"""The `identity` schema. Tables with patient data are under row-level security (see the migration)."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nafas_core.db import Base
from nafas_core.enums.channel import Channel
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language, UserRole
from nafas_identity.enums import CareStatus, ConsentKind, Sex

SCHEMA = "identity"


def _enum(enum_cls, name: str) -> ENUM:
    # stored as the enum's values ("doctor"), not its member names ("DOCTOR")
    return ENUM(enum_cls, name=name, schema=SCHEMA, values_callable=lambda e: [m.value for m in e], create_type=False)


def _id() -> Mapped[uuid.UUID]:
    # generated client-side: an INSERT under row-level security cannot always
    # read its own row back, so nothing should depend on RETURNING the key
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    # set in Python too, so an insert never has to read the value back (see Base)
    return mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now())


class User(Base):
    """A web account: a doctor's, a patient's, or staff's. The role decides the portal."""

    __tablename__ = "users"
    __table_args__ = (
        # one account per address, whatever its capitalisation
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(_enum(UserRole, "user_role"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Specialization(Base):
    """
    What a doctor practises, and so what the patient assistant may discuss.

    `scope_description` is given verbatim to the scope classifier, and
    `always_escalate` lists topics that go to the doctor however they are asked.
    """

    __tablename__ = "specializations"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_en: Mapped[str] = mapped_column(Text)
    name_ar: Mapped[str] = mapped_column(Text)
    scope_description: Mapped[str] = mapped_column(Text)
    in_scope_topics: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    always_escalate: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))


class Doctor(Base):
    """
    A doctor's identity and profile. How they take bookings (hours, time zone,
    slot length) belongs to the scheduling service, in scheduling.booking_settings.
    """

    __tablename__ = "doctors"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"), unique=True)
    full_name_en: Mapped[str] = mapped_column(Text)
    full_name_ar: Mapped[str] = mapped_column(Text)
    specialization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.specializations.id"))
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)), default=lambda: ["ar"], server_default=text("ARRAY['ar']::varchar[]")
    )
    created_at: Mapped[datetime] = _created_at()


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[uuid.UUID] = _id()
    # their web login; None for a patient known only through a channel
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"), unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[Sex | None] = mapped_column(_enum(Sex, "sex"))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    preferred_language: Mapped[Language] = mapped_column(
        _enum(Language, "language"), default=Language.ARABIC, server_default="ar"
    )
    # chosen by the patient: the dialect replies are spoken (and written) in,
    # and the built-in voice that speaks them; None until they choose
    dialect: Mapped[SpokenDialect | None] = mapped_column(_enum(SpokenDialect, "spoken_dialect"))
    voice: Mapped[VoiceGender | None] = mapped_column(_enum(VoiceGender, "voice_gender"))
    created_at: Mapped[datetime] = _created_at()


class PatientChannel(Base):
    """One way to reach a patient: their Telegram chat, their email address."""

    __tablename__ = "patient_channels"
    __table_args__ = (UniqueConstraint("channel", "external_id"), {"schema": SCHEMA})

    id: Mapped[uuid.UUID] = _id()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.patients.id", ondelete="CASCADE"), index=True)
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"))
    external_id: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DoctorPatient(Base):
    """
    A patient under a doctor's care: the access boundary for every clinical
    query. A doctor sees a patient's records only through one of these rows.
    """

    __tablename__ = "doctor_patients"
    __table_args__ = {"schema": SCHEMA}

    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.doctors.id"), primary_key=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.patients.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    status: Mapped[CareStatus] = mapped_column(
        _enum(CareStatus, "care_status"), default=CareStatus.ACTIVE, server_default="active"
    )
    first_seen_at: Mapped[datetime] = _created_at()


class Consent(Base):
    """
    A patient's consent. Data processing is given once, to the platform
    (no doctor); AI chat and session recording are given to one doctor.
    """

    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint("(kind = 'data_processing') = (doctor_id IS NULL)", name="doctor_only_where_needed"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = _id()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.patients.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.doctors.id"))
    kind: Mapped[ConsentKind] = mapped_column(_enum(ConsentKind, "consent_kind"))
    granted_at: Mapped[datetime] = _created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[Channel | None] = mapped_column(_enum(Channel, "channel"))
    # what shows the consent was given: a message id, a signed form's key
    evidence: Mapped[str | None] = mapped_column(Text)
