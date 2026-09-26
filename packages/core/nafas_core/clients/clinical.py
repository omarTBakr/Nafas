"""The clinical-records service's internal API: a patient's record with one doctor, and search over it."""

import uuid

import httpx

from nafas_core.clients.base import InternalClient
from nafas_core.config import get_setting


class ClinicalClient(InternalClient):
    service = "clinical-records"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(base_url=get_setting().clinical_url, timeout=15.0))

    async def search(self, patient_id: uuid.UUID, doctor_id: uuid.UUID, query: str, audience: str, k: int = 6) -> list[dict]:
        body = {"patient_id": str(patient_id), "doctor_id": str(doctor_id), "query": query, "audience": audience, "k": k}
        return (await self.request("POST", "/internal/v1/search", json=body)).json()

    async def new_document(self, doctor_id: uuid.UUID, patient_id: uuid.UUID, body: dict) -> dict:
        return (await self.request("POST", f"/internal/v1/doctors/{doctor_id}/patients/{patient_id}/documents", json=body)).json()

    async def uploaded(self, doctor_id: uuid.UUID, document_id: uuid.UUID) -> dict:
        return (await self.request("POST", f"/internal/v1/doctors/{doctor_id}/documents/{document_id}/uploaded")).json()

    async def documents(self, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[dict]:
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/patients/{patient_id}/documents")).json()

    async def download(self, doctor_id: uuid.UUID, document_id: uuid.UUID) -> dict:
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/documents/{document_id}/download")).json()

    async def history(self, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[dict]:
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/patients/{patient_id}/history")).json()

    async def add_entry(self, doctor_id: uuid.UUID, patient_id: uuid.UUID, body: dict) -> dict:
        return (await self.request("POST", f"/internal/v1/doctors/{doctor_id}/patients/{patient_id}/history", json=body)).json()

    async def set_visibility(self, doctor_id: uuid.UUID, source_type: str, record_id: uuid.UUID, visibility: str) -> None:
        path = f"/internal/v1/doctors/{doctor_id}/records/{source_type}/{record_id}/visibility"
        await self.request("PATCH", path, json={"visibility": visibility})

    async def patient_documents(self, patient_id: uuid.UUID, doctor_id: uuid.UUID | None = None) -> list[dict]:
        params = {"doctor_id": str(doctor_id)} if doctor_id else None
        return (await self.request("GET", f"/internal/v1/patients/{patient_id}/documents", params=params)).json()


_clinical: ClinicalClient | None = None


def get_clinical() -> ClinicalClient:
    global _clinical
    if _clinical is None:
        _clinical = ClinicalClient()
    return _clinical


def set_clinical(client: ClinicalClient | None) -> None:
    global _clinical
    _clinical = client
