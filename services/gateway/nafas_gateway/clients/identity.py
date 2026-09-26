import uuid
from dataclasses import dataclass

import httpx

from nafas_core.config import get_setting
from nafas_core.enums.identity import UserRole
from nafas_gateway.clients.base import InternalClient


@dataclass
class Account:
    user_id: uuid.UUID
    email: str
    role: UserRole
    doctor_id: uuid.UUID | None
    patient_id: uuid.UUID | None = None


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def _account(body: dict) -> Account:
    return Account(
        user_id=uuid.UUID(body["user_id"]),
        email=body["email"],
        role=UserRole(body["role"]),
        doctor_id=_uuid(body.get("doctor_id")),
        patient_id=_uuid(body.get("patient_id")),
    )


class IdentityClient(InternalClient):
    """The identity service's internal API. For accounts, None means "no such account", never an error."""

    service = "identity"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(base_url=get_setting().identity_url, timeout=5.0))

    async def verify(self, email: str, password: str) -> Account | None:
        response = await self.request(
            "POST", "/internal/v1/auth/verify", expected=(200, 401), json={"email": email, "password": password}
        )
        return None if response.status_code == 401 else _account(response.json())

    async def get_user(self, user_id: uuid.UUID) -> Account | None:
        response = await self.request("GET", f"/internal/v1/users/{user_id}", expected=(200, 404))
        return None if response.status_code == 404 else _account(response.json())

    async def sign_up_patient(self, form: dict) -> Account:
        return _account((await self.request("POST", "/internal/v1/patients", json=form)).json())

    async def profile(self, patient_id: uuid.UUID) -> dict:
        return (await self.request("GET", f"/internal/v1/patients/{patient_id}/profile")).json()

    async def update_profile(self, patient_id: uuid.UUID, changes: dict) -> dict:
        return (await self.request("PATCH", f"/internal/v1/patients/{patient_id}/profile", json=changes)).json()

    async def specializations(self) -> list[dict]:
        return (await self.request("GET", "/internal/v1/specializations")).json()

    async def doctors(self, specialization: str | None = None) -> list[dict]:
        params = {"specialization": specialization} if specialization else None
        return (await self.request("GET", "/internal/v1/doctors", params=params)).json()

    async def doctor(self, doctor_id: uuid.UUID) -> dict:
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}")).json()

    async def patient_names(self, doctor_id: uuid.UUID, patient_ids: list[uuid.UUID]) -> dict[str, str]:
        if not patient_ids:
            return {}
        response = await self.request(
            "GET", f"/internal/v1/doctors/{doctor_id}/patients", params=[("ids", str(i)) for i in patient_ids]
        )
        return {row["patient_id"]: row["full_name"] for row in response.json()}

    async def ensure_care_link(self, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> None:
        await self.request("POST", "/internal/v1/care-links", json={"doctor_id": str(doctor_id), "patient_id": str(patient_id)})


_identity: IdentityClient | None = None


def get_identity() -> IdentityClient:
    global _identity
    if _identity is None:
        _identity = IdentityClient()

    return _identity


def set_identity(client: IdentityClient | None) -> None:
    """Replaces the process-wide client; tests pass one over a mock transport, and None to reset."""
    global _identity
    _identity = client
