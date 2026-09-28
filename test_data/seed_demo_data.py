"""Seed synthetic doctors, patients, care links, consents, and schedules.

Run from the repository root after migrations and specialization seeding:

    uv run python test_data/seed_demo_data.py

All records use the ``.test`` domain and are synthetic. The script is
idempotent for its deterministic email addresses and writes login details to
``test_data/demo_manifest.json``.
"""

import asyncio
import json
from datetime import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from nafas_core.db import session_scope
from nafas_core.enums.dialect import SpokenDialect, VoiceGender
from nafas_core.enums.identity import Language
from nafas_identity.enums import CareStatus, ConsentKind
from nafas_identity.logic import consents
from nafas_identity.logic.accounts import create_doctor_account, register_patient_account
from nafas_identity.logic.seed import seed_specializations
from nafas_identity.models import Doctor, DoctorPatient, Patient, User
from nafas_scheduling.enums import AvailabilityMode
from nafas_scheduling.models import AvailabilityRule, BookingSettings

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "demo_manifest.json"
PASSWORD = "NafasDemo!2026"

DOCTORS = [
    ("cardiology", "Dr Salma Hassan", "د. سلمى حسن", "salma.hassan"),
    ("dermatology", "Dr Omar Nassar", "د. عمر نصار", "omar.nassar"),
    ("pediatrics", "Dr Lina Adel", "د. لينا عادل", "lina.adel"),
    ("internal_medicine", "Dr Karim Youssef", "د. كريم يوسف", "karim.youssef"),
    ("obstetrics_gynecology", "Dr Nour Farouk", "د. نور فاروق", "nour.farouk"),
    ("orthopedics", "Dr Hany Mahmoud", "د. هاني محمود", "hany.mahmoud"),
    ("ophthalmology", "Dr Reem Tarek", "د. ريم طارق", "reem.tarek"),
    ("psychiatry", "Dr Yara Samir", "د. يارا سمير", "yara.samir"),
]

PATIENTS = [
    ("Mariam Ali", "مريم علي", "mariam.ali", Language.ARABIC, SpokenDialect.EGYPTIAN, VoiceGender.FEMALE),
    ("Youssef Adel", "يوسف عادل", "youssef.adel", Language.ARABIC, SpokenDialect.SAUDI, VoiceGender.MALE),
    ("Huda Karim", "هدى كريم", "huda.karim", Language.ARABIC, SpokenDialect.LEBANESE, VoiceGender.FEMALE),
    ("Adam Nabil", "آدم نبيل", "adam.nabil", Language.ENGLISH, SpokenDialect.EGYPTIAN, VoiceGender.MALE),
    ("Sara Mostafa", "سارة مصطفى", "sara.mostafa", Language.ARABIC, SpokenDialect.MOROCCAN, VoiceGender.FEMALE),
    ("Khaled Taha", "خالد طه", "khaled.taha", Language.ARABIC, SpokenDialect.SUDANESE, VoiceGender.MALE),
    ("Noha Sameh", "نهى سامح", "noha.sameh", Language.ARABIC, SpokenDialect.SYRIAN, VoiceGender.FEMALE),
    ("Daniel George", "دانيال جورج", "daniel.george", Language.ENGLISH, SpokenDialect.IRAQI, VoiceGender.MALE),
    ("Rana Fathy", "رانا فتحي", "rana.fathy", Language.ARABIC, SpokenDialect.PALESTINIAN, VoiceGender.FEMALE),
    ("Hassan Wael", "حسن وائل", "hassan.wael", Language.ARABIC, SpokenDialect.LIBYAN, VoiceGender.MALE),
    ("Aya Reda", "آية رضا", "aya.reda", Language.ARABIC, SpokenDialect.TUNISIAN, VoiceGender.FEMALE),
    ("Mina Fawzy", "مينا فوزي", "mina.fawzy", Language.ARABIC, SpokenDialect.BAHRAINI, VoiceGender.MALE),
    ("Layla Hatem", "ليلى حاتم", "layla.hatem", Language.ARABIC, SpokenDialect.ALGERIAN, VoiceGender.FEMALE),
    ("Fadi Nader", "فادي نادر", "fadi.nader", Language.ARABIC, SpokenDialect.YEMENI, VoiceGender.MALE),
    ("Jana Saeed", "جنى سعيد", "jana.saeed", Language.ARABIC, SpokenDialect.SAUDI, VoiceGender.FEMALE),
    ("Peter Sameh", "بيتر سامح", "peter.sameh", Language.ENGLISH, SpokenDialect.EGYPTIAN, VoiceGender.MALE),
]

# Two patients per doctor; the final four are shared across two doctors.
CARE_LINKS = {
    0: [0, 1, 8],
    1: [2, 3, 9],
    2: [4, 5, 10],
    3: [6, 7, 11],
    4: [8, 12],
    5: [9, 13],
    6: [10, 14],
    7: [11, 15],
}

SCHEDULES = [
    ("Africa/Cairo", 1, time(9), time(13)),
    ("Africa/Cairo", 2, time(14), time(18)),
    ("Asia/Riyadh", 3, time(10), time(14)),
    ("Africa/Cairo", 4, time(16), time(20)),
    ("Africa/Cairo", 5, time(9), time(13)),
    ("Africa/Cairo", 0, time(15), time(19)),
    ("Africa/Cairo", 2, time(10), time(14)),
    ("Africa/Cairo", 6, time(12), time(16)),
]


def email(local_part: str, role: str) -> str:
    return f"{local_part}.{role}@example.test"


async def get_or_create_doctor(code: str, name_en: str, name_ar: str, local_part: str) -> Doctor:
    address = email(local_part, "doctor")
    async with session_scope() as session:
        existing = await session.scalar(select(Doctor).join(User).where(User.email == address))
        if existing is not None:
            return existing
        return await create_doctor_account(
            session,
            email=address,
            password=PASSWORD,
            full_name_en=name_en,
            full_name_ar=name_ar,
            specialization_code=code,
        )


async def get_or_create_patient(
    name_en: str,
    name_ar: str,
    local_part: str,
    language: Language,
    dialect: SpokenDialect,
    voice: VoiceGender,
) -> Patient:
    address = email(local_part, "patient")
    async with session_scope() as session:
        existing_user_id = await session.scalar(select(User.id).where(User.email == address))
        if existing_user_id is not None:
            patient_id = await session.scalar(text("SELECT identity.patient_id_for_user(:user)"), {"user": existing_user_id})
            if patient_id is None:
                raise RuntimeError(f"account exists but has no patient row: {address}")
            async with session_scope(patient_id=patient_id) as patient_session:
                existing = await patient_session.get(Patient, patient_id)
                if existing is None:
                    raise RuntimeError(f"patient row is not visible in its own scope: {address}")
                return existing
        account = await register_patient_account(
            session,
            email=address,
            password=PASSWORD,
            full_name=name_ar,
            preferred_language=language,
            dialect=dialect,
            voice=voice,
            consent_evidence="synthetic-demo-data-processing-v1",
        )
        patient = await session.get(Patient, account.patient_id)
        assert patient is not None
        return patient


async def link_patient(doctor_id: UUID, patient_id: UUID) -> None:
    async with session_scope(doctor_id=doctor_id) as session:
        link = await session.get(DoctorPatient, (doctor_id, patient_id))
        if link is None:
            session.add(DoctorPatient(doctor_id=doctor_id, patient_id=patient_id, status=CareStatus.ACTIVE))
        await consents.grant(
            session,
            patient_id=patient_id,
            doctor_id=doctor_id,
            kind=ConsentKind.AI_CHAT,
            evidence="synthetic-demo-ai-chat-v1",
        )


async def configure_schedule(doctor_id: UUID, timezone: str, weekday: int, start: time, end: time) -> None:
    async with session_scope(doctor_id=doctor_id) as session:
        settings = await session.get(BookingSettings, doctor_id)
        if settings is None:
            session.add(
                BookingSettings(
                    doctor_id=doctor_id,
                    timezone=timezone,
                    slot_minutes=20,
                    buffer_minutes=0,
                    min_notice_minutes=0,
                    horizon_days=60,
                    hold_minutes=10,
                )
            )
        else:
            settings.timezone = timezone
            settings.min_notice_minutes = 0

        existing = await session.scalar(
            select(AvailabilityRule).where(
                AvailabilityRule.doctor_id == doctor_id,
                AvailabilityRule.weekday == weekday,
                AvailabilityRule.start_local == start,
                AvailabilityRule.end_local == end,
            )
        )
        if existing is None:
            session.add(
                AvailabilityRule(
                    doctor_id=doctor_id,
                    weekday=weekday,
                    start_local=start,
                    end_local=end,
                    mode=AvailabilityMode.BOTH,
                    slot_minutes=20,
                )
            )


async def seed() -> dict:
    async with session_scope() as session:
        await seed_specializations(session)

    doctors = [await get_or_create_doctor(*definition) for definition in DOCTORS]
    patients = [await get_or_create_patient(*definition) for definition in PATIENTS]

    for index, doctor in enumerate(doctors):
        timezone, weekday, start, end = SCHEDULES[index]
        await configure_schedule(doctor.id, timezone, weekday, start, end)
        for patient_index in CARE_LINKS[index]:
            await link_patient(doctor.id, patients[patient_index].id)

    manifest = {
        "password": PASSWORD,
        "doctors": [
            {
                "email": email(definition[3], "doctor"),
                "name_en": definition[1],
                "specialization": definition[0],
                "doctor_id": str(doctor.id),
            }
            for definition, doctor in zip(DOCTORS, doctors, strict=True)
        ],
        "patients": [
            {
                "email": email(definition[2], "patient"),
                "name_en": definition[0],
                "patient_id": str(patient.id),
                "dialect": definition[4].value,
                "language": definition[3].value,
            }
            for definition, patient in zip(PATIENTS, patients, strict=True)
        ],
        "care_links": sum(len(patient_indexes) for patient_indexes in CARE_LINKS.values()),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    result = asyncio.run(seed())
    print(f"Created or reused {len(result['doctors'])} doctors and {len(result['patients'])} patients.")
    print(f"Created or reused {result['care_links']} doctor-patient links.")
    print(f"Credentials and IDs written to {MANIFEST}")
