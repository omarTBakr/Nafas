"""The identity service's internal API: reached by other services only, behind the internal token."""

import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from nafas_core.db import session_scope
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language, UserRole
from nafas_core.internal_api import require_internal_token
from nafas_identity.exceptions import AccountExistsError, WeakPasswordError
from nafas_identity.logic.accounts import AuthenticatedUser, authenticate, get_user, register_patient_account
from nafas_identity.logic.directory import DoctorCard, ensure_care_link, list_doctors, list_specializations
from nafas_identity.logic.profile import PatientProfile, get_profile, update_profile
from nafas_identity.models import Patient


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


class ProfileOut(BaseModel):
    patient_id: uuid.UUID
    full_name: str
    phone: str | None
    preferred_language: Language
    dialect: SpokenDialect | None
    voice: VoiceGender | None


class ProfileChanges(BaseModel):
    """Only the fields sent are changed; send null to clear dialect, voice or phone."""

    full_name: str | None = None
    phone: str | None = None
    preferred_language: Language | None = None
    dialect: SpokenDialect | None = None
    voice: VoiceGender | None = None


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

    async with session_scope(patient_id=patient_id) as session:
        profile = await update_profile(session, patient_id, **sent)
    if profile is None:
        raise HTTPException(status_code=404, detail="no such patient")

    return _profile(profile)


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


@router.get("/doctors/{doctor_id}/patients", response_model=list[PatientName])
async def patient_names(doctor_id: uuid.UUID, ids: list[uuid.UUID] = Query(default=[])) -> list[PatientName]:
    """Names of the doctor's own patients among `ids`; anyone not under their care is simply absent."""
    async with session_scope(doctor_id=doctor_id) as session:
        rows = (await session.execute(select(Patient.id, Patient.full_name).where(Patient.id.in_(ids)))).all()

    return [PatientName(patient_id=pid, full_name=name) for pid, name in rows]


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
