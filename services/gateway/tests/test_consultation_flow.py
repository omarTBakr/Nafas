"""A recorded visit through the gateway and the real services: record, review, approve, and what each side then sees."""

import uuid

from temporalio.testing import ActivityEnvironment

from nafas_consultation.activities import ConsultationActivities
from nafas_consultation.prompts import soap
from nafas_consultation.schemas import ConsultationRef
from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.identity import get_identity
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.stt.fake import FakeSTT

from .conftest import DOCTOR_PASSWORD, browser, sign_up
from .test_records_flow import booked, storage  # noqa: F401  (a fixture)

NOTE = {
    "subjective": "Chest tightness on stairs for a month.",
    "objective": "BP 140/90.",
    "assessment": "Suspected stable angina.",
    "plan": "Exercise ECG; aspirin 81 mg daily.",
    "diagnoses": [{"name": "Stable angina", "status": "suspected"}],
    "medications": [{"name": "Aspirin", "dose": "81 mg", "frequency": "daily", "change": "started"}],
    "allergies": [],
    "patient_summary": "هنعمل رسم قلب بالمجهود، وتبدأ أسبرين ٨١ مجم كل يوم.",
    "uncertain": [],
}


async def test_a_recorded_visit_reaches_the_record_only_once_the_doctor_approves(
    doctor_id,
    storage,
    consultation_events,  # noqa: F811
):
    async with browser() as sara, browser() as doctor, browser() as stranger:
        await sign_up(sara)
        patient_id = await booked(sara, doctor_id)
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})
        await sign_up(stranger, email="omar@example.com", name="عمر")

        started = await doctor.post(f"/api/doctor/patients/{patient_id}/consultations", json={})
        cid = started.json()["consultation_id"]
        part = await doctor.post(
            f"/api/doctor/consultations/{cid}/parts",
            json={"index": 0, "mime": "audio/webm", "offset_seconds": 0, "size_bytes": 5},
        )
        await storage.put(part.json()["upload_url"].removeprefix("memory://put/").split("?")[0], b"audio", "audio/webm")
        finished = await doctor.post(f"/api/doctor/consultations/{cid}/finish")
        assert finished.json()["status"] == "transcribing" and consultation_events.events == [("finished", cid)]
        # a patient's session is not a doctor's
        assert (await stranger.get(f"/api/doctor/consultations/{cid}")).status_code == 403

        # what the workflow does, step by step
        activities = ConsultationActivities(
            storage,
            FakeSTT("عندي كتمة في صدري لما بطلع السلم"),
            FakeLLM([tool_use_message(soap.TOOL["name"], NOTE)]),
            get_identity(),
            get_clinical(),
            "summary-model",
        )
        ref = ConsultationRef(cid, str(doctor_id))
        await ActivityEnvironment().run(activities.transcribe, ref)
        await activities.draft(ref)

        review = (await doctor.get("/api/doctor/consultations")).json()
        draft = (await doctor.get(f"/api/doctor/consultations/{cid}")).json()
        timeline = (await doctor.get(f"/api/doctor/patients/{patient_id}/timeline")).json()
        before = (await sara.get("/api/me/records")).json()

        bad = await doctor.post(f"/api/doctor/consultations/{cid}/approve", json={"note": {"plan": 5}})
        approved = await doctor.post(
            f"/api/doctor/consultations/{cid}/approve", json={"note": draft["draft"], "share_with_patient": True}
        )
        await activities.file(ref)
        after = (await sara.get("/api/me/records")).json()
        history = (await doctor.get(f"/api/doctor/patients/{patient_id}/history")).json()

    assert [c["consultation_id"] for c in review] == [cid]
    assert draft["transcript"][0]["text"].startswith("عندي كتمة") and draft["draft"]["assessment"] == NOTE["assessment"]
    assert [i["status"] for i in timeline["items"] if i["type"] == "consultation"] == ["draft_ready"]
    assert before["history"] == []
    assert bad.status_code == 422
    assert approved.json()["status"] == "filing" and consultation_events.events[-1] == ("approved", cid)
    assert [e["content"] for e in after["history"]] == [NOTE["patient_summary"]]
    assert after["history"][0]["doctor_id"] == str(doctor_id)
    assert {e["kind"] for e in history} == {"visit_summary", "diagnosis", "medication"}


async def test_a_doctor_cannot_record_someone_not_under_their_care(doctor_id):
    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        patient_id = (await sara.get("/api/auth/me")).json()["patient_id"]
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})

        refused = await doctor.post(f"/api/doctor/patients/{patient_id}/consultations", json={})
        missing = await doctor.get(f"/api/doctor/consultations/{uuid.uuid4()}")

    assert refused.status_code == 403 and refused.json()["reason"] == "not_under_care"
    assert missing.status_code == 404
