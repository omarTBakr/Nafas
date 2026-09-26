"""Documents end to end: the upload link, ingestion on Temporal with the real activities, and search by audience."""

import uuid

import httpx
import pytest
from temporalio.worker import Worker

import nafas_core.config
from nafas_clinical.activities import ClinicalActivities
from nafas_clinical.api import app as clinical_app
from nafas_clinical.events import TemporalIngestionEvents, set_events
from nafas_clinical.logic.extraction import ocr_available
from nafas_clinical.workflows import WORKFLOWS
from nafas_core.clients.identity import IdentityClient, set_identity
from nafas_core.interfaces.embeddings.factory import set_embeddings
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_core.interfaces.llm.fake import FakeLLM
from nafas_core.interfaces.storage.factory import set_storage
from nafas_core.interfaces.storage.fake import InMemoryStorage
from nafas_identity.api import app as identity_app

from .conftest import png, text_pdf

needs_ocr = pytest.mark.skipif(not ocr_available(), reason="OCR needs tesseract")


@pytest.fixture
async def api(clinic, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    nafas_core.config._settings_instance = None
    storage = InMemoryStorage()
    set_storage(storage)
    set_embeddings(FakeEmbeddings())
    set_identity(IdentityClient(httpx.AsyncClient(transport=httpx.ASGITransport(app=identity_app), base_url="http://identity")))
    headers = {"X-Internal-Token": "internal-secret"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=clinical_app), base_url="http://c", headers=headers) as client:
        client.storage = storage
        yield client
    set_storage(None)
    set_embeddings(None)
    set_identity(None)


async def upload(api, clinic, data: bytes, mime: str, filename: str) -> dict:
    created = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/documents",
        json={"kind": "report", "filename": filename, "mime": mime, "size_bytes": len(data)},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # what the browser does with the link
    key = body["upload_url"].removeprefix("memory://put/").split("?")[0]
    await api.storage.put(key, data, mime)
    return body["document"]


async def test_an_upload_link_is_only_for_a_patient_under_care(api, clinic, ingestion_events):
    early = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/documents",
        json={"filename": "echo.pdf", "mime": "application/pdf", "size_bytes": 10},
    )
    document_id = early.json()["document"]["document_id"]
    not_yet = await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/documents/{document_id}/uploaded")
    stranger = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.other_patient_id}/documents",
        json={"filename": "x.pdf", "mime": "application/pdf", "size_bytes": 10},
    )
    wrong_type = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/documents",
        json={"filename": "x.exe", "mime": "application/x-msdownload", "size_bytes": 10},
    )

    assert early.json()["upload_url"].startswith(f"memory://put/doctor/{clinic.doctor_id}/patient/{clinic.patient_id}/documents/")
    assert not_yet.status_code == 409
    assert stranger.status_code == 409 and stranger.json()["reason"] == "not_under_care"
    assert wrong_type.status_code == 422
    assert ingestion_events.uploaded_ids == []


async def test_a_pdf_is_read_indexed_and_found_by_the_doctor_but_not_yet_the_patient(api, clinic, temporal, task_queue):
    set_events(TemporalIngestionEvents(temporal, task_queue))
    activities = ClinicalActivities(api.storage, FakeEmbeddings(), FakeLLM(), "vision-model")
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        document = await upload(
            api, clinic, text_pdf(["Echocardiogram report", "Ejection fraction 55 percent"]), "application/pdf", "echo.pdf"
        )
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/documents/{document['document_id']}/uploaded")
        assert await temporal.get_workflow_handle(f"ingest-{document['document_id']}").result() == "indexed"

    [listed] = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/documents")).json()
    assert (listed["status"], listed["page_count"]) == ("indexed", 1)

    def search(audience):
        return api.post(
            "/internal/v1/search",
            json={
                "patient_id": str(clinic.patient_id),
                "doctor_id": str(clinic.doctor_id),
                "query": "ejection fraction",
                "audience": audience,
            },
        )

    doctor_hits = (await search("doctor")).json()
    assert doctor_hits and "Ejection fraction 55 percent" in doctor_hits[0]["content"]
    assert doctor_hits[0]["details"]["filename"] == "echo.pdf"
    assert (await search("patient")).json() == []

    await api.patch(
        f"/internal/v1/doctors/{clinic.doctor_id}/records/document/{document['document_id']}/visibility",
        json={"visibility": "patient_visible"},
    )
    assert (await search("patient")).json()[0]["source_id"] == document["document_id"]
    shared = (await api.get(f"/internal/v1/patients/{clinic.patient_id}/documents")).json()
    assert [d["filename"] for d in shared] == ["echo.pdf"]


@needs_ocr
async def test_an_image_gets_ocr_and_a_labelled_description(api, clinic, temporal, task_queue):
    set_events(TemporalIngestionEvents(temporal, task_queue))
    llm = FakeLLM(["A photo of a printed prescription listing bisoprolol."])
    activities = ClinicalActivities(api.storage, FakeEmbeddings(), llm, "vision-model")
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        document = await upload(api, clinic, png(["PRESCRIPTION", "Bisoprolol 5 mg"]), "image/png", "rx.png")
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/documents/{document['document_id']}/uploaded")
        assert await temporal.get_workflow_handle(f"ingest-{document['document_id']}").result() == "indexed"

    [listed] = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/documents")).json()
    assert listed["ai_description"] == "A photo of a printed prescription listing bisoprolol."
    assert listed["ai_label"] == "AI description, not a read"
    # the model was shown the image itself
    [request] = llm.requests
    assert request["model"] == "vision-model" and request["messages"][0]["content"][0]["type"] == "image"
    hits = (
        await api.post(
            "/internal/v1/search",
            json={
                "patient_id": str(clinic.patient_id),
                "doctor_id": str(clinic.doctor_id),
                "query": "Bisoprolol",
                "audience": "doctor",
            },
        )
    ).json()
    assert "Bisoprolol" in hits[0]["content"] and "[AI description, not a read]" in hits[0]["content"]


async def test_a_broken_file_is_marked_failed_with_the_reason(api, clinic, temporal, task_queue):
    set_events(TemporalIngestionEvents(temporal, task_queue))
    activities = ClinicalActivities(api.storage, FakeEmbeddings(), None, "vision-model")
    async with Worker(temporal, task_queue=task_queue, workflows=WORKFLOWS, activities=activities.all()):
        document = await upload(api, clinic, b"%PDF-1.4 this is not really a pdf", "application/pdf", "broken.pdf")
        await api.post(f"/internal/v1/doctors/{clinic.doctor_id}/documents/{document['document_id']}/uploaded")
        assert await temporal.get_workflow_handle(f"ingest-{document['document_id']}").result() == "failed"

    [listed] = (await api.get(f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/documents")).json()
    assert listed["status"] == "failed" and "not a readable PDF" in listed["error"]


async def test_notes_are_searchable_at_once_and_another_doctor_sees_none(api, clinic):
    added = await api.post(
        f"/internal/v1/doctors/{clinic.doctor_id}/patients/{clinic.patient_id}/history",
        json={"kind": "allergy", "content": "Allergic to penicillin.", "visibility": "patient_visible"},
    )
    theirs = await api.get(f"/internal/v1/doctors/{clinic.other_doctor_id}/patients/{clinic.patient_id}/history")
    hits = await api.post(
        "/internal/v1/search",
        json={
            "patient_id": str(clinic.patient_id),
            "doctor_id": str(clinic.doctor_id),
            "query": "penicillin",
            "audience": "patient",
        },
    )

    assert added.status_code == 201 and added.json()["kind"] == "allergy"
    assert theirs.json() == []
    assert hits.json()[0]["content"] == "Allergic to penicillin."
    assert uuid.UUID(hits.json()[0]["source_id"]) == uuid.UUID(added.json()["entry_id"])
