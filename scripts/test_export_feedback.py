"""The feedback export reads only patients who opted in, and writes nothing that names them."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nafas_consultation.enums import ConsultationStatus
from nafas_consultation.logic import consultations
from nafas_conversation.enums import EscalationReason
from nafas_conversation.logic import escalations, messages
from nafas_core.db import session_scope
from nafas_identity.enums import ConsentKind
from nafas_identity.logic import consents
from nafas_identity.logic.accounts import create_doctor_account, register_patient_account
from nafas_identity.logic.directory import ensure_care_link
from nafas_identity.logic.seed import seed_specializations
from scripts.export_feedback import deidentify, export, name_patterns

SALT = "a-test-salt-of-some-length"


def test_names_contacts_numbers_and_dates_are_replaced():
    names = name_patterns(["منى علي حسن", "Dr Karim Adel"])

    cleaned = deidentify(
        "أنا منى، رقمي 01012345678 وإيميلي mona@example.com، الزيارة 30/09/2026 مع Karim. عندي خفقان من ٣ أيام",
        names,
    )

    assert "منى" not in cleaned and "Karim" not in cleaned
    assert "[number]" in cleaned and "[email]" in cleaned and "[date]" in cleaned
    # what the question was about survives
    assert "عندي خفقان من ٣ أيام" in cleaned


async def test_only_opted_in_patients_are_exported_de_identified(database, tmp_path):
    async with session_scope() as session:
        await seed_specializations(session)
        doctor = await create_doctor_account(
            session,
            email="heart@example.com",
            password="doctor password 1",
            full_name_en="Dr Karim Adel",
            full_name_ar="د. كريم عادل",
            specialization_code="cardiology",
        )
        ids = []
        for email, name in (("mona@example.com", "منى علي"), ("omar@example.com", "عمر سامي")):
            account = await register_patient_account(session, email=email, password="patient password 1", full_name=name)
            ids.append(account.patient_id)
    mona, omar = ids
    async with session_scope(patient_id=mona) as session:
        await consents.grant(session, patient_id=mona, kind=ConsentKind.SERVICE_IMPROVEMENT)
    async with session_scope(doctor_id=doctor.id) as session:
        for patient in ids:
            await ensure_care_link(session, doctor_id=doctor.id, patient_id=patient)

    for patient, name in ((mona, "منى"), (omar, "عمر")):
        conversation = await messages.open_conversation(patient, doctor.id)
        question, reply = uuid.uuid4(), uuid.uuid4()
        await messages.add_patient_message(patient, question, conversation, f"أنا {name}، ينفع أزود جرعة الدوا؟")
        await messages.add_assistant_message(
            patient, reply, conversation, text="هسأل د. كريم.", model="m", prompt_version="v1", tokens_in=1, tokens_out=1
        )
        await messages.rate_reply(patient, doctor.id, reply, "down")
        escalation = uuid.uuid4()
        await escalations.open_escalation(
            escalation_id=escalation,
            patient_id=patient,
            doctor_id=doctor.id,
            conversation_id=conversation,
            message_id=question,
            reason=EscalationReason.UNCLEAR,
            workflow_id=f"e-{escalation}",
        )
        await escalations.answer(doctor.id, escalation, f"يا {name} متزودش الجرعة قبل الزيارة.")
        async with session_scope(doctor_id=doctor.id) as session:
            recording = await consents.record_session_recording(
                session, patient_id=patient, doctor_id=doctor.id, evidence="verbal"
            )
            visit = await consultations.create(session, doctor_id=doctor.id, patient_id=patient, consent_id=recording.id)
            visit.transcript = [{"start": 0, "end": 5, "text": f"إزيك يا {name}"}]
            visit.draft = {"subjective": f"{name} has palpitations.", "plan": "Holter."}
            visit.approved = {"subjective": "Patient has palpitations.", "plan": "Holter."}
            consultations.mark(visit, ConsultationStatus.APPROVED)

    manifest = await export(database, tmp_path, SALT, since=datetime(1970, 1, 1, tzinfo=UTC))

    assert manifest["consenting_patients"] == 1 and manifest["review_required"] is True
    assert manifest["counts"] == {
        "chat_ratings.jsonl": 1,
        "escalations.jsonl": 1,
        "visit_notes.jsonl": 1,
        "eval_candidates.jsonl": 2,
    }
    written = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.jsonl"))
    for secret in ("منى", "عمر", "كريم", "Karim", str(mona), str(omar), str(doctor.id)):
        assert secret not in written, f"{secret} reached the export"
    [rating] = [json.loads(line) for line in (tmp_path / "chat_ratings.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rating["rating"] == "down" and rating["question"] == "أنا [name]، ينفع أزود جرعة الدوا؟"
    [visit] = [json.loads(line) for line in (tmp_path / "visit_notes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert visit["edited"] is True and visit["draft"]["subjective"] == "[name] has palpitations."

    engine = create_async_engine(database)
    try:
        async with engine.connect() as db:
            logged = (await db.execute(text("SELECT count(*) FROM audit.audit_log WHERE action = 'export_feedback'"))).scalar()
    finally:
        await engine.dispose()
    assert logged == 1
