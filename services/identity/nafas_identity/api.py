"""The identity service's internal API: reached by other services only, behind the internal token."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from nafas_core import audit
from nafas_core.db import session_scope
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language, UserRole
from nafas_core.internal_api import require_internal_token
from nafas_identity.enums import CareStatus, ConsentKind
from nafas_identity.exceptions import AccountExistsError, ConsentNotFoundError, WeakPasswordError
from nafas_identity.logic import consents
from nafas_identity.logic.accounts import AuthenticatedUser, authenticate, get_user, register_patient_account
from nafas_identity.logic.directory import (
    DoctorCard,
    doctor_scope,
    ensure_care_link,
    list_doctors,
    list_specializations,
    under_care,
    under_care_as_doctor,
)
from nafas_identity.logic.profile import PatientProfile, get_profile, update_profile
from nafas_identity.models import DoctorPatient, Patient


class Credentials(BaseModel):
    email: str
    password: str


class Account(BaseModel):
    user_id: uuid.UUID
    email: str
    role: UserRole
    doctor_id: uuid.UUID | None
    patient_id: uuid.UUID | None


class PatientSignUp(BaseModel):
    email: str
    password: str
    full_name: str
    preferred_language: Language = Language.ARABIC
    phone: str | None = None
    dialect: SpokenDialect | None = None
    voice: VoiceGender | None = None
    # what the patient agreed to (the consent text's version); sign-up needs it
    data_processing_consent: str


class ProfileOut(BaseModel):
    patient_id: uuid.UUID
    full_name: str
    phone: str | None
    preferred_language: Language
    dialect: SpokenDialect | None
    voice: VoiceGender | None
    email: str | None = None
    email_notices: bool = True


class ProfileChanges(BaseModel):
    """Only the fields sent are changed; send null to clear dialect, voice or phone."""

    full_name: str | None = None
    phone: str | None = None
    preferred_language: Language | None = None
    dialect: SpokenDialect | None = None
    voice: VoiceGender | None = None
    email_notices: bool | None = None


def _profile(profile: PatientProfile) -> ProfileOut:
    return ProfileOut(**profile.__dict__)


class DoctorOut(BaseModel):
    doctor_id: uuid.UUID
    full_name_en: str
    full_name_ar: str
    specialization_code: str
    specialization_en: str
    specialization_ar: str
    languages: list[str]


class SpecializationOut(BaseModel):
    code: str
    name_en: str
    name_ar: str


class CareLink(BaseModel):
    doctor_id: uuid.UUID
    patient_id: uuid.UUID


def _doctor(card: DoctorCard) -> DoctorOut:
    return DoctorOut(**card.__dict__)


def _account(user: AuthenticatedUser) -> Account:
    return Account(user_id=user.user_id, email=user.email, role=user.role, doctor_id=user.doctor_id, patient_id=user.patient_id)


router = APIRouter(prefix="/internal/v1")


@router.post("/auth/verify", response_model=Account)
async def verify_credentials(credentials: Credentials) -> Account:
    """The account for these credentials, or 401 — the same 401 whatever was wrong."""
    async with session_scope() as session:
        user = await authenticate(session, credentials.email, credentials.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    return _account(user)


@router.post("/patients", response_model=Account, status_code=201)
async def sign_up_patient(form: PatientSignUp) -> Account:
    """409 when the email is taken, 422 when the password is too weak."""
    try:
        async with session_scope() as session:
            user = await register_patient_account(
                session,
                email=form.email,
                password=form.password,
                full_name=form.full_name,
                preferred_language=form.preferred_language,
                phone=form.phone,
                dialect=form.dialect,
                voice=form.voice,
                consent_evidence=form.data_processing_consent,
            )
    except AccountExistsError as exc:
        raise HTTPException(status_code=409, detail="an account with this email already exists") from exc
    except WeakPasswordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _account(user)


@router.get("/patients/{patient_id}/profile", response_model=ProfileOut)
async def read_profile(patient_id: uuid.UUID) -> ProfileOut:
    async with session_scope(patient_id=patient_id) as session:
        profile = await get_profile(session, patient_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="no such patient")

    return _profile(profile)


@router.patch("/patients/{patient_id}/profile", response_model=ProfileOut)
async def change_profile(patient_id: uuid.UUID, changes: ProfileChanges) -> ProfileOut:
    sent = changes.model_dump(exclude_unset=True)
    if sent.get("full_name") is None:
        sent.pop("full_name", None)
    if sent.get("preferred_language") is None:
        sent.pop("preferred_language", None)
    if sent.get("email_notices") is None:
        sent.pop("email_notices", None)

    async with session_scope(patient_id=patient_id) as session:
        profile = await update_profile(session, patient_id, **sent)
    if profile is None:
        raise HTTPException(status_code=404, detail="no such patient")

    return _profile(profile)


class ConsentIn(BaseModel):
    kind: ConsentKind
    doctor_id: uuid.UUID | None = None
    evidence: str | None = None


class ConsentOut(BaseModel):
    consent_id: uuid.UUID
    kind: ConsentKind
    doctor_id: uuid.UUID | None
    granted_at: datetime
    evidence: str | None


def _consent(c) -> ConsentOut:
    return ConsentOut(consent_id=c.id, kind=c.kind, doctor_id=c.doctor_id, granted_at=c.granted_at, evidence=c.evidence)


@router.get("/patients/{patient_id}/consents", response_model=list[ConsentOut])
async def patient_consents(patient_id: uuid.UUID) -> list[ConsentOut]:
    """The patient's consents in force, in their own scope."""
    async with session_scope(patient_id=patient_id) as session:
        return [_consent(c) for c in await consents.in_force(session, patient_id)]


@router.post("/patients/{patient_id}/consents", response_model=ConsentOut, status_code=201)
async def grant_consent(patient_id: uuid.UUID, consent: ConsentIn) -> ConsentOut:
    try:
        async with session_scope(patient_id=patient_id) as session:
            return _consent(
                await consents.grant(
                    session, patient_id=patient_id, kind=consent.kind, doctor_id=consent.doctor_id, evidence=consent.evidence
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/patients/{patient_id}/consents/{consent_id}/revoke", status_code=204)
async def revoke_consent(patient_id: uuid.UUID, consent_id: uuid.UUID) -> None:
    try:
        async with session_scope(patient_id=patient_id) as session:
            await consents.revoke(session, patient_id, consent_id)
    except ConsentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="no such consent") from exc


class RecordingConsentIn(BaseModel):
    evidence: str = Field(min_length=1, max_length=200)


@router.post("/doctors/{doctor_id}/patients/{patient_id}/recording-consent", response_model=ConsentOut, status_code=201)
async def recording_consent(doctor_id: uuid.UUID, patient_id: uuid.UUID, body: RecordingConsentIn) -> ConsentOut:
    """The patient agreed, in the room, to this one session being recorded; recorded by their doctor."""
    async with session_scope(doctor_id=doctor_id) as session:
        if not await under_care_as_doctor(session, doctor_id, patient_id):
            raise HTTPException(status_code=409, detail="this patient is not under your care")
        return _consent(
            await consents.record_session_recording(session, patient_id=patient_id, doctor_id=doctor_id, evidence=body.evidence)
        )


@router.get("/patients/{patient_id}/may-chat/{doctor_id}")
async def may_chat(patient_id: uuid.UUID, doctor_id: uuid.UUID) -> dict:
    """Whether the patient's consents let the assistant of this doctor talk with them."""
    async with session_scope(patient_id=patient_id) as session:
        return {"allowed": await consents.may_chat(session, patient_id, doctor_id)}


@router.get("/users/{user_id}", response_model=Account)
async def read_user(user_id: uuid.UUID) -> Account:
    """An active account; 404 when it is gone or disabled, which ends its sessions."""
    async with session_scope() as session:
        user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="no such active account")

    return _account(user)


@router.get("/specializations", response_model=list[SpecializationOut])
async def specializations() -> list[SpecializationOut]:
    async with session_scope() as session:
        return [SpecializationOut(code=s.code, name_en=s.name_en, name_ar=s.name_ar) for s in await list_specializations(session)]


@router.get("/doctors", response_model=list[DoctorOut])
async def doctors(specialization: str | None = None) -> list[DoctorOut]:
    async with session_scope() as session:
        return [_doctor(card) for card in await list_doctors(session, specialization_code=specialization)]


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
async def doctor(doctor_id: uuid.UUID) -> DoctorOut:
    async with session_scope() as session:
        found = await list_doctors(session, doctor_id=doctor_id)
    if not found:
        raise HTTPException(status_code=404, detail="no such doctor")

    return _doctor(found[0])


class PatientName(BaseModel):
    patient_id: uuid.UUID
    full_name: str


class PatientCard(BaseModel):
    patient_id: uuid.UUID
    full_name: str
    date_of_birth: date | None
    sex: str | None
    phone: str | None
    preferred_language: Language
    first_seen_at: datetime


@router.get("/doctors/{doctor_id}/roster", response_model=list[PatientCard])
async def roster(doctor_id: uuid.UUID) -> list[PatientCard]:
    """The patients under this doctor's care, newest to them first."""
    async with session_scope(doctor_id=doctor_id) as session:
        rows = (
            await session.execute(
                select(Patient, DoctorPatient.first_seen_at)
                .join(DoctorPatient, DoctorPatient.patient_id == Patient.id)
                .where(DoctorPatient.doctor_id == doctor_id, DoctorPatient.status == CareStatus.ACTIVE)
                .order_by(DoctorPatient.first_seen_at.desc())
            )
        ).all()
    if rows:
        await audit.record(
            service="identity",
            actor=audit.Actor.DOCTOR,
            actor_id=doctor_id,
            action="read_roster",
            resource_type="patient",
            doctor_id=doctor_id,
            detail={"count": len(rows)},
        )
    return [
        PatientCard(
            patient_id=p.id,
            full_name=p.full_name,
            date_of_birth=p.date_of_birth,
            sex=p.sex.value if p.sex else None,
            phone=p.phone,
            preferred_language=p.preferred_language,
            first_seen_at=first_seen,
        )
        for p, first_seen in rows
    ]


@router.get("/doctors/{doctor_id}/patients", response_model=list[PatientName])
async def patient_names(doctor_id: uuid.UUID, ids: list[uuid.UUID] = Query(default=[])) -> list[PatientName]:
    """Names of the doctor's own patients among `ids`; anyone not under their care is simply absent."""
    async with session_scope(doctor_id=doctor_id) as session:
        rows = (await session.execute(select(Patient.id, Patient.full_name).where(Patient.id.in_(ids)))).all()

    if rows:
        await audit.record(
            service="identity",
            actor=audit.Actor.DOCTOR,
            actor_id=doctor_id,
            action="read_patient_names",
            resource_type="patient",
            doctor_id=doctor_id,
            detail={"patient_ids": [str(pid) for pid, _ in rows]},
        )
    return [PatientName(patient_id=pid, full_name=name) for pid, name in rows]


class ScopeOut(BaseModel):
    code: str
    name_en: str
    name_ar: str
    scope_description: str
    in_scope_topics: list[str]
    always_escalate: list[str]


@router.get("/doctors/{doctor_id}/scope", response_model=ScopeOut)
async def scope_of(doctor_id: uuid.UUID) -> ScopeOut:
    """What the doctor's specialization covers, and what always goes to the doctor: read by the safety gates."""
    async with session_scope() as session:
        spec = await doctor_scope(session, doctor_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="no such doctor")
    return ScopeOut(
        code=spec.code,
        name_en=spec.name_en,
        name_ar=spec.name_ar,
        scope_description=spec.scope_description,
        in_scope_topics=list(spec.in_scope_topics),
        always_escalate=list(spec.always_escalate),
    )


@router.get("/patients/{patient_id}/care/{doctor_id}")
async def care(patient_id: uuid.UUID, doctor_id: uuid.UUID) -> dict:
    """Whether the patient is under this doctor's care now."""
    async with session_scope(patient_id=patient_id) as session:
        return {"active": await under_care(session, doctor_id, patient_id)}


@router.post("/care-links", status_code=204)
async def care_link(link: CareLink) -> None:
    """Idempotent: the patient is under the doctor's care afterwards, whether or not they were before."""
    async with session_scope(doctor_id=link.doctor_id) as session:
        await ensure_care_link(session, link.doctor_id, link.patient_id)


app = FastAPI(title="Nafas identity (internal)")
# on the router's inclusion, so an endpoint added later is covered by being added at all
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
