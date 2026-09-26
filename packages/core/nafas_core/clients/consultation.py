"""The consultation service's internal API: recording a visit, its draft note, and the doctor's approval."""

import uuid

import httpx

from nafas_core.clients.base import InternalClient
from nafas_core.config import get_setting


class ConsultationClient(InternalClient):
    service = "consultation"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(base_url=get_setting().consultation_url, timeout=15.0))

    def _at(self, doctor_id: uuid.UUID, rest: str) -> str:
        return f"/internal/v1/doctors/{doctor_id}/{rest}"

    async def start(self, doctor_id: uuid.UUID, patient_id: uuid.UUID, body: dict) -> dict:
        return (await self.request("POST", self._at(doctor_id, f"patients/{patient_id}/consultations"), json=body)).json()

    async def new_part(self, doctor_id: uuid.UUID, consultation_id: uuid.UUID, body: dict) -> dict:
        return (await self.request("POST", self._at(doctor_id, f"consultations/{consultation_id}/parts"), json=body)).json()

    async def finish(self, doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> dict:
        return (await self.request("POST", self._at(doctor_id, f"consultations/{consultation_id}/finish"))).json()

    async def awaiting_review(self, doctor_id: uuid.UUID) -> list[dict]:
        return (await self.request("GET", self._at(doctor_id, "consultations"))).json()

    async def for_patient(self, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[dict]:
        return (await self.request("GET", self._at(doctor_id, f"patients/{patient_id}/consultations"))).json()

    async def detail(self, doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> dict:
        return (await self.request("GET", self._at(doctor_id, f"consultations/{consultation_id}"))).json()

    async def approve(self, doctor_id: uuid.UUID, consultation_id: uuid.UUID, body: dict) -> dict:
        return (await self.request("POST", self._at(doctor_id, f"consultations/{consultation_id}/approve"), json=body)).json()

    async def discard(self, doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> dict:
        return (await self.request("POST", self._at(doctor_id, f"consultations/{consultation_id}/discard"))).json()


_consultation: ConsultationClient | None = None


def get_consultation() -> ConsultationClient:
    global _consultation
    if _consultation is None:
        _consultation = ConsultationClient()
    return _consultation


def set_consultation(client: ConsultationClient | None) -> None:
    global _consultation
    _consultation = client
