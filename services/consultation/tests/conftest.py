import uuid
from dataclasses import dataclass

import httpx
import pytest

import nafas_core.config
from nafas_clinical.api import app as clinical_app
from nafas_consultation.api import app as consultation_app
from nafas_core.clients.clinical import ClinicalClient, set_clinical
from nafas_core.clients.identity import IdentityClient, set_identity
from nafas_core.db import session_scope
from nafas_core.interfaces.embeddings.factory import set_embeddings
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_core.interfaces.storage.factory import set_storage
from nafas_core.interfaces.storage.fake import InMemoryStorage
from nafas_identity.api import app as identity_app
from nafas_identity.logic.accounts import create_doctor_account, register_patient_account
from nafas_identity.logic.directory import ensure_care_link
from nafas_identity.logic.seed import seed_specializations


@dataclass
class Clinic:
    doctor_id: uuid.UUID
    other_doctor_id: uuid.UUID
    patient_id: uuid.UUID
    other_patient_id: uuid.UUID


@pytest.fixture
async def clinic(database) -> Clinic:
    """Two doctors; a patient under the first one's care, and a second patient under no one's."""
    async with session_scope() as session:
        await seed_specializations(session)
        ids = []
        for email in ("heart@example.com", "other@example.com"):
            doctor = await create_doctor_account(
                session,
                email=email,
                password="doctor password 1",
                full_name_en="Dr",
                full_name_ar="د",
                specialization_code="cardiology",
            )
            ids.append(doctor.id)
        patients = []
        for email in ("p1@example.com", "p2@example.com"):
            account = await register_patient_account(session, email=email, password="patient password 1", full_name="م")
            patients.append(account.patient_id)
    async with session_scope(doctor_id=ids[0]) as session:
        await ensure_care_link(session, doctor_id=ids[0], patient_id=patients[0])
    return Clinic(ids[0], ids[1], patients[0], patients[1])


def _asgi(app, name: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{name}")


@pytest.fixture
async def api(clinic, monkeypatch):
    """The consultation API, with identity and clinical-records in-process and storage in memory."""
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    nafas_core.config._settings_instance = None
    storage = InMemoryStorage()
    set_storage(storage)
    set_embeddings(FakeEmbeddings())
    identity, clinical = IdentityClient(_asgi(identity_app, "identity")), ClinicalClient(_asgi(clinical_app, "clinical"))
    set_identity(identity)
    set_clinical(clinical)
    headers = {"X-Internal-Token": "internal-secret"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=consultation_app), base_url="http://c", headers=headers
    ) as client:
        client.storage, client.identity, client.clinical = storage, identity, clinical
        yield client
    set_storage(None)
    set_embeddings(None)
    set_identity(None)
    set_clinical(None)
