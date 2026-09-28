"""A patient's visits, each read on its own, through the gateway and the real services."""

import uuid
from datetime import time

from temporalio.testing import ActivityEnvironment

from nafas_consultation.activities import ConsultationActivities
from nafas_consultation.prompts import soap
from nafas_consultation.schemas import ConsultationRef
from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.identity import get_identity
from nafas_core.interfaces.llm.fake import FakeLLM, tool_use_message
from nafas_core.interfaces.stt.fake import FakeSTT

from .conftest import DOCTOR_PASSWORD, browser, next_wednesday, sign_up
from .test_consultation_flow import NOTE
from .test_records_flow import booked


async def test_each_visit_holds_what_was_filed_under_it(doctor_id, storage, consultation_events):
    async with browser() as sara, browser() as omar, browser() as doctor:
        await sign_up(sara)
        patient_id = await booked(sara, doctor_id)
        later = await sara.post(
            "/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(19)).isoformat()}
        )
        await sara.post(f"/api/appointments/{later.json()['appointment_id']}/confirm")
        await sign_up(omar, email="omar@example.com", name="عمر")
        omars = await omar.post(
            "/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(18)).isoformat()}
        )
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})

        listed = (await doctor.get(f"/api/doctor/patients/{patient_id}/visits")).json()
        first, second = listed["visits"][1]["appointment_id"], listed["visits"][0]["appointment_id"]

        # a recording, a note and a document from the first visit's page; one note from the patient's file
        started = await doctor.post(f"/api/doctor/patients/{patient_id}/consultations", json={"appointment_id": first})
        cid = started.json()["consultation_id"]
        activities = ConsultationActivities(
            storage,
            FakeSTT("عندي كتمة في صدري"),
            FakeLLM([tool_use_message(soap.TOOL["name"], NOTE)]),
            get_identity(),
            get_clinical(),
            "summary-model",
        )
        ref = ConsultationRef(cid, str(doctor_id))
        part = await doctor.post(
            f"/api/doctor/consultations/{cid}/parts",
            json={"index": 0, "mime": "audio/webm", "offset_seconds": 0, "size_bytes": 5},
        )
        await storage.put(part.json()["upload_url"].removeprefix("memory://put/").split("?")[0], b"audio", "audio/webm")
        await doctor.post(f"/api/doctor/consultations/{cid}/finish")
        await ActivityEnvironment().run(activities.transcribe, ref)
        await activities.draft(ref)
        draft = (await doctor.get(f"/api/doctor/consultations/{cid}")).json()
        await doctor.post(f"/api/doctor/consultations/{cid}/approve", json={"note": draft["draft"]})
        await activities.file(ref)

        note = await doctor.post(
            f"/api/doctor/patients/{patient_id}/history", json={"content": "Walks 20 minutes a day.", "appointment_id": first}
        )
        upload = await doctor.post(
            f"/api/doctor/patients/{patient_id}/documents",
            json={"kind": "lab", "filename": "lipids.pdf", "mime": "application/pdf", "size_bytes": 9, "appointment_id": first},
        )
        await doctor.post(f"/api/doctor/patients/{patient_id}/history", json={"content": "Prefers morning visits."})

        visits = (await doctor.get(f"/api/doctor/patients/{patient_id}/visits")).json()
        one = (await doctor.get(f"/api/doctor/patients/{patient_id}/visits/{first}")).json()
        two = (await doctor.get(f"/api/doctor/patients/{patient_id}/visits/{second}")).json()
        # Omar's visit is the doctor's, but not Sara's; nothing is filed under it from her file
        crossed = await doctor.get(f"/api/doctor/patients/{patient_id}/visits/{omars.json()['appointment_id']}")
        misfiled = await doctor.post(
            f"/api/doctor/patients/{patient_id}/history",
            json={"content": "x", "appointment_id": omars.json()["appointment_id"]},
        )
        unknown = await doctor.get(f"/api/doctor/patients/{patient_id}/visits/{uuid.uuid4()}")
        # a patient cannot read the doctor's view of their visits
        own = await sara.get(f"/api/doctor/patients/{patient_id}/visits")

    assert [v["appointment_id"] for v in visits["visits"]] == [second, first]
    counts = {v["appointment_id"]: (v["recordings"], v["notes"], v["documents"]) for v in visits["visits"]}
    # the recording's filed note is four entries: summary, diagnosis, medication, transcript; plus the note
    assert counts == {first: (1, 5, 1), second: (0, 0, 0)}
    assert note.status_code == 201 and upload.status_code == 201
    assert one["appointment"]["appointment_id"] == first and one["timezone"] == "Africa/Cairo"
    assert [c["consultation_id"] for c in one["consultations"]] == [cid]
    assert "Walks 20 minutes a day." in [e["content"] for e in one["history"]]
    assert "Prefers morning visits." not in [e["content"] for e in one["history"]]
    assert [d["filename"] for d in one["documents"]] == ["lipids.pdf"]
    assert two["consultations"] == two["history"] == two["documents"] == []
    assert crossed.status_code == 404 and misfiled.status_code == 404
    assert unknown.status_code == 404
    assert own.status_code == 403
