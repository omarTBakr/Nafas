"""A doctor's record of a patient, through the gateway and the real services: notes, an upload, and what the patient sees."""

from datetime import time

from .conftest import DOCTOR_PASSWORD, browser, next_wednesday, sign_up


async def booked(sara, doctor_id) -> str:
    """Sara books and confirms, which puts her under the doctor's care; her patient id."""
    held = await sara.post("/api/appointments", json={"doctor_id": str(doctor_id), "start": next_wednesday(time(17)).isoformat()})
    await sara.post(f"/api/appointments/{held.json()['appointment_id']}/confirm")
    return held.json()["patient_id"]


async def test_the_doctor_keeps_a_record_and_shares_part_of_it(doctor_id, storage, ingestion_events):
    async with browser() as sara, browser() as doctor, browser() as stranger:
        await sign_up(sara)
        patient_id = await booked(sara, doctor_id)
        await sign_up(stranger, email="omar@example.com", name="عمر")
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})

        shared = await doctor.post(
            f"/api/doctor/patients/{patient_id}/history",
            json={"content": "Target blood pressure below 130/80.", "visibility": "patient_visible"},
        )
        await doctor.post(f"/api/doctor/patients/{patient_id}/history", json={"content": "Consider anxiety component."})
        started = (
            await doctor.post(
                f"/api/doctor/patients/{patient_id}/documents",
                json={"kind": "report", "filename": "echo.pdf", "mime": "application/pdf", "size_bytes": 12},
            )
        ).json()
        key = started["upload_url"].removeprefix("memory://put/").split("?")[0]
        await storage.put(key, b"%PDF-1.4 ...", "application/pdf")
        document_id = started["document"]["document_id"]
        finished = await doctor.post(f"/api/doctor/documents/{document_id}/uploaded")
        await doctor.patch(f"/api/doctor/records/document/{document_id}/visibility", json={"visibility": "patient_visible"})

        history = (await doctor.get(f"/api/doctor/patients/{patient_id}/history")).json()
        mine = (await sara.get("/api/me/documents")).json()
        opened = await sara.get(f"/api/me/documents/{document_id}/download")
        await doctor.patch(f"/api/doctor/records/document/{document_id}/visibility", json={"visibility": "doctor_only"})
        hidden = await sara.get(f"/api/me/documents/{document_id}/download")
        refused = await stranger.get(f"/api/doctor/patients/{patient_id}/history")

    assert shared.status_code == 201
    assert [e["content"] for e in history] == ["Consider anxiety component.", "Target blood pressure below 130/80."]
    assert finished.json()["status"] == "uploaded" and ingestion_events.uploaded_ids == [document_id]
    assert [d["filename"] for d in mine] == ["echo.pdf"]
    assert opened.json()["url"].startswith("memory://get/") and hidden.status_code == 404
    assert refused.status_code == 403


async def test_a_doctor_cannot_write_into_the_record_of_someone_not_under_their_care(doctor_id, storage):
    async with browser() as sara, browser() as doctor:
        await sign_up(sara)
        patient_id = (await sara.get("/api/auth/me")).json()["patient_id"]
        await doctor.post("/api/auth/login", json={"email": "heart@example.com", "password": DOCTOR_PASSWORD})

        note = await doctor.post(f"/api/doctor/patients/{patient_id}/history", json={"content": "x"})

    assert note.status_code == 403 and note.json()["reason"] == "not_under_care"
