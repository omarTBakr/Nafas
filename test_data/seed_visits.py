"""Seed one synthetic patient's history of visits with one doctor: a full use case for the visits pages.

Run from the repository root with the stack up (Postgres, S3 and the
embeddings service reachable from the host), after ``seed_demo_data.py``:

    uv run python test_data/seed_visits.py

The story, for Dr Salma Hassan (cardiology) and Mariam Ali:

1. ~8 weeks ago, in person: palpitations at night. The visit was recorded;
   the doctor approved the note (PVCs suspected, bisoprolol started) and
   shared the plain-language summary. An ECG report and a note are filed
   under the visit.
2. ~4 weeks ago, online follow-up: better on bisoprolol. A Holter summary
   and a lipid panel (shared with Mariam) and a note are filed under it.
3. ~3 weeks ago: cancelled by the patient.
4. ~2 weeks ago: no-show.
5. Next week: confirmed, to review the results.

Plus one note in her file that belongs to no visit (family history).

Every id is derived from a fixed namespace, so running it again writes
nothing twice. Past visits are written directly (booking only makes future
ones); history and documents go through clinical-records' own logic and are
indexed, so the doctor's assistant can find them.
"""

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# the containers index with the embeddings service; so does this, from the host
os.environ.setdefault("EMBEDDINGS_PROVIDER", "self_hosted")

from sqlalchemy import select  # noqa: E402

from nafas_clinical.enums import DocumentKind, DocumentStatus, HistoryKind, SourceType, Visibility  # noqa: E402
from nafas_clinical.logic import records, search  # noqa: E402
from nafas_clinical.logic.records import document_key  # noqa: E402
from nafas_clinical.models import Document, HistoryEntry  # noqa: E402
from nafas_consultation.enums import ConsultationStatus  # noqa: E402
from nafas_consultation.logic import transcript  # noqa: E402
from nafas_consultation.logic.note import Note, entries  # noqa: E402
from nafas_consultation.models import Consultation  # noqa: E402
from nafas_core.db import session_scope  # noqa: E402
from nafas_core.interfaces.embeddings import get_embeddings  # noqa: E402
from nafas_core.interfaces.storage.factory import get_storage  # noqa: E402
from nafas_identity.enums import ConsentKind  # noqa: E402
from nafas_identity.logic import consents  # noqa: E402
from nafas_scheduling.enums import AppointmentMode, AppointmentStatus  # noqa: E402
from nafas_scheduling.models import Appointment  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_demo_data import DOCTORS, PATIENTS, seed  # noqa: E402

NAMESPACE = uuid.UUID("6f1c3a52-9d0e-4c1b-8a57-3e2f5b7d9a10")
CAIRO = ZoneInfo("Africa/Cairo")
DOCTOR_EMAIL = f"{DOCTORS[0][3]}.doctor@example.test"
PATIENT_EMAIL = f"{PATIENTS[0][2]}.patient@example.test"


def sid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "/".join(parts))


def weeks_ago(weeks: int, at: time) -> datetime:
    """A Tuesday (the doctor's clinic day) `weeks` weeks back, at `at` in Cairo."""
    today = datetime.now(CAIRO).date()
    tuesday = today - timedelta(days=(today.weekday() - 1) % 7) - timedelta(weeks=weeks)
    return datetime.combine(tuesday, at, tzinfo=CAIRO).astimezone(UTC)


def next_tuesday(at: time) -> datetime:
    today = datetime.now(CAIRO).date()
    return datetime.combine(today + timedelta(days=(1 - today.weekday()) % 7 or 7), at, tzinfo=CAIRO).astimezone(UTC)


VISITS = [
    # key, start, status, mode, reason
    ("palpitations", weeks_ago(8, time(9)), AppointmentStatus.COMPLETED, AppointmentMode.IN_PERSON, "خفقان في القلب بالليل"),
    ("follow-up", weeks_ago(4, time(9, 40)), AppointmentStatus.COMPLETED, AppointmentMode.ONLINE, "متابعة بعد البيسوبرولول"),
    ("cancelled", weeks_ago(3, time(10, 20)), AppointmentStatus.CANCELLED, AppointmentMode.IN_PERSON, "متابعة التحاليل"),
    ("no-show", weeks_ago(2, time(11)), AppointmentStatus.NO_SHOW, AppointmentMode.IN_PERSON, "متابعة التحاليل"),
    ("results", next_tuesday(time(12, 20)), AppointmentStatus.CONFIRMED, AppointmentMode.IN_PERSON, "مراجعة الهولتر والدهون"),
]

TRANSCRIPT = [
    {"start": 0.0, "end": 6.5, "text": "أهلًا يا مريم، إيه اللي تاعبك؟"},
    {"start": 6.5, "end": 18.0, "text": "بحس إن قلبي بيدق جامد وبيقف ثانية كده، خصوصًا بالليل وأنا نايمة."},
    {"start": 18.0, "end": 26.0, "text": "من إمتى؟ وبتشربي قهوة كتير؟"},
    {"start": 26.0, "end": 36.0, "text": "من حوالي شهرين، وبشرب تلات فناجين قهوة في اليوم."},
    {"start": 36.0, "end": 52.0, "text": "رسم القلب فيه ضربات زيادة بسيطة من البطين. هنبدأ بيسوبرولول ٢.٥ مجم ونقلل القهوة."},
]

NOTE = Note(
    subjective="Palpitations for two months, mostly at night, described as a pause then a strong beat. Three coffees a day.",
    objective="BP 128/82, HR 88 regular. ECG: sinus rhythm with occasional unifocal PVCs.",
    assessment="Symptomatic premature ventricular contractions, likely benign; caffeine a contributor.",
    plan="Bisoprolol 2.5 mg once daily. Cut caffeine to one cup. 24-hour Holter and lipid panel before follow-up in 4 weeks.",
    diagnoses=[{"name": "Premature ventricular contractions", "status": "suspected"}],
    medications=[{"name": "Bisoprolol", "dose": "2.5 mg", "frequency": "once daily", "change": "started"}],
    allergies=[],
    patient_summary="ضربات القلب الزيادة غالبًا بسيطة. هتبدئي بيسوبرولول ٢.٥ مجم مرة في اليوم، وقللي القهوة لفنجان واحد، "
    "واعملي هولتر ٢٤ ساعة وتحليل دهون قبل المتابعة بعد ٤ أسابيع.",
)

DOCUMENTS = [
    # key, visit, kind, filename, text, shared
    (
        "ecg",
        "palpitations",
        DocumentKind.REPORT,
        "ecg_report.txt",
        "12-lead ECG. Sinus rhythm 86 bpm. PR 160 ms, QRS 90 ms, QTc 420 ms. "
        "Occasional unifocal premature ventricular complexes. No ST changes.",
        False,
    ),
    (
        "holter",
        "follow-up",
        DocumentKind.REPORT,
        "holter_24h.txt",
        "24-hour Holter on bisoprolol 2.5 mg. Mean HR 66, min 48 asleep, max 118 walking. "
        "PVC burden 1.2% (about 1,100 in 24 h), unifocal, no couplets or runs. No pauses over 2 s.",
        False,
    ),
    (
        "lipids",
        "follow-up",
        DocumentKind.LAB,
        "lipid_panel.txt",
        "Fasting lipid panel. Total cholesterol 212 mg/dL, LDL 138 mg/dL, HDL 48 mg/dL, triglycerides 130 mg/dL.",
        True,
    ),
]

NOTES = [
    # key, visit (or None), text, shared
    ("caffeine", "palpitations", "Advised to cut caffeine to one cup a day; to keep a symptom diary.", False),
    ("better", "follow-up", "Palpitations much less frequent on bisoprolol. HR 64 on video, no dizziness.", False),
    ("ldl", "follow-up", "LDL 138: diet and exercise first; recheck in 3 months before considering a statin.", True),
    ("family", None, "Family history: father had a myocardial infarction at 55.", False),
]


async def ids() -> tuple[uuid.UUID, uuid.UUID]:
    """The demo doctor's and patient's ids, seeding the demo accounts if they are not there yet."""
    manifest = await seed()
    doctor = next(d for d in manifest["doctors"] if d["email"] == DOCTOR_EMAIL)
    patient = next(p for p in manifest["patients"] if p["email"] == PATIENT_EMAIL)
    return uuid.UUID(doctor["doctor_id"]), uuid.UUID(patient["patient_id"])


async def appointments(doctor_id: uuid.UUID, patient_id: uuid.UUID) -> dict[str, uuid.UUID]:
    out = {}
    async with session_scope(doctor_id=doctor_id) as session:
        for key, start, status, mode, reason in VISITS:
            appointment_id = sid("appointment", key)
            out[key] = appointment_id
            existing = await session.get(Appointment, appointment_id)
            if existing is not None:
                # a re-run next week: the "upcoming" visit moves with the calendar
                if status is AppointmentStatus.CONFIRMED and existing.starts_at < datetime.now(UTC):
                    existing.starts_at, existing.ends_at = start, start + timedelta(minutes=20)
                continue
            session.add(
                Appointment(
                    id=appointment_id,
                    doctor_id=doctor_id,
                    patient_id=patient_id,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=20),
                    status=status,
                    mode=mode,
                    reason_for_visit=reason,
                )
            )
    return out


async def add_entry(doctor_id: uuid.UUID, patient_id: uuid.UUID, body: dict, occurred_at: datetime) -> None:
    """One history entry as clinical-records files it: the row, then its passages for search."""
    async with session_scope(doctor_id=doctor_id) as session:
        entry, new = await records.add_history(
            session,
            doctor_id=doctor_id,
            patient_id=patient_id,
            kind=HistoryKind(body["kind"]),
            content=body["content"],
            visibility=Visibility(body["visibility"]),
            occurred_at=occurred_at,
            structured=body.get("structured") or {},
            source_type=body.get("source_type"),
            source_id=uuid.UUID(body["source_id"]) if body.get("source_id") else None,
            created_by=doctor_id if body.get("source_type") is None else None,
            entry_id=uuid.UUID(body["entry_id"]),
            appointment_id=body.get("appointment_id"),
        )
        if not new:
            return
        details = {"kind": body["kind"], "occurred_at": occurred_at.isoformat()}
        if body.get("source_type"):
            details |= {"source": body["source_type"], "source_id": body["source_id"]}
        await search.index(
            session,
            get_embeddings(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            source_type=SourceType.HISTORY,
            source_id=entry.id,
            text=body["content"],
            visibility=entry.visibility,
            details=details,
        )


async def recorded_visit(doctor_id: uuid.UUID, patient_id: uuid.UUID, appointment_id: uuid.UUID, start: datetime) -> None:
    """The first visit's recording, approved and filed as the consultation workflow would."""
    consultation_id = sid("consultation", "palpitations")
    async with session_scope(doctor_id=doctor_id) as session:
        if await session.get(Consultation, consultation_id) is None:
            consent = await consents.grant(
                session,
                patient_id=patient_id,
                doctor_id=doctor_id,
                kind=ConsentKind.SESSION_RECORDING,
                evidence="synthetic-demo: verbal, in the room",
            )
            session.add(
                Consultation(
                    id=consultation_id,
                    doctor_id=doctor_id,
                    patient_id=patient_id,
                    appointment_id=appointment_id,
                    consent_id=consent.id,
                    status=ConsultationStatus.APPROVED,
                    source="in_person",
                    transcript=TRANSCRIPT,
                    draft=NOTE.model_dump(),
                    approved=NOTE.model_dump(),
                    share_with_patient=True,
                    model="synthetic-demo",
                    prompt_version="synthetic-demo",
                    started_at=start + timedelta(minutes=2),
                    approved_at=start + timedelta(minutes=45),
                )
            )
    for body in entries(consultation_id, NOTE, True, transcript.for_prompt(TRANSCRIPT)):
        await add_entry(doctor_id, patient_id, body, start + timedelta(minutes=2))


async def document(doctor_id: uuid.UUID, patient_id: uuid.UUID, appointment_id: uuid.UUID, at: datetime, spec: tuple) -> None:
    """A text report uploaded under a visit, read and indexed."""
    key, _, kind, filename, content, shared = spec
    document_id = sid("document", key)
    data = content.encode()
    async with session_scope(doctor_id=doctor_id) as session:
        if await session.get(Document, document_id) is not None:
            return
        row = Document(
            id=document_id,
            doctor_id=doctor_id,
            patient_id=patient_id,
            kind=kind,
            filename=filename,
            mime="text/plain",
            size_bytes=len(data),
            object_key=document_key(doctor_id, patient_id, document_id, "text/plain"),
            uploaded_by=doctor_id,
            appointment_id=appointment_id,
            extracted_text=content,
            page_count=1,
            status=DocumentStatus.INDEXED,
            visibility=Visibility.PATIENT_VISIBLE if shared else Visibility.DOCTOR_ONLY,
            created_at=at,
        )
        session.add(row)
        await get_storage().put(row.object_key, data, "text/plain")
        await search.index(
            session,
            get_embeddings(),
            patient_id=patient_id,
            doctor_id=doctor_id,
            source_type=SourceType.DOCUMENT,
            source_id=document_id,
            text=content,
            visibility=row.visibility,
            details={"filename": filename, "page": 1},
        )


async def main() -> None:
    doctor_id, patient_id = await ids()
    visits = await appointments(doctor_id, patient_id)
    starts = {key: start for key, start, *_ in VISITS}

    await recorded_visit(doctor_id, patient_id, visits["palpitations"], starts["palpitations"])
    for spec in DOCUMENTS:
        visit = spec[1]
        await document(doctor_id, patient_id, visits[visit], starts[visit] + timedelta(minutes=30), spec)
    for key, visit, text, shared in NOTES:
        body = {
            "entry_id": str(sid("note", key)),
            "kind": "note",
            "content": text,
            "visibility": "patient_visible" if shared else "doctor_only",
            "appointment_id": visits[visit] if visit else None,
        }
        at = starts[visit] + timedelta(minutes=15) if visit else weeks_ago(9, time(9))
        await add_entry(doctor_id, patient_id, body, at)

    async with session_scope(doctor_id=doctor_id) as session:
        filed = await session.scalars(select(HistoryEntry.id).where(HistoryEntry.patient_id == patient_id))
        count = len(filed.all())
    print(f"{len(visits)} visits for {PATIENTS[0][0]} with {DOCTORS[0][1]}; {count} history entries in her file.")
    print(f"Log in as {DOCTOR_EMAIL} (password in test_data/demo_manifest.json) and open My patients → {PATIENTS[0][1]}.")


if __name__ == "__main__":
    asyncio.run(main())
