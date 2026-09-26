import uuid
from datetime import datetime

import httpx

from nafas_core.clients.base import InternalClient
from nafas_core.config import get_setting


class SchedulingClient(InternalClient):
    """The scheduling service's internal API; refusals arrive as UpstreamRefusal with the reason."""

    service = "scheduling"

    def __init__(self, client: httpx.AsyncClient | None = None):
        super().__init__(client or httpx.AsyncClient(base_url=get_setting().scheduling_url, timeout=10.0))

    async def booking_info(self, doctor_id: uuid.UUID) -> dict:
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/booking-info")).json()

    async def slots(self, doctor_id: uuid.UUID, start: datetime, end: datetime, mode: str, limit: int | None) -> list[dict]:
        params = {"start": start.isoformat(), "end": end.isoformat(), "mode": mode}
        if limit:
            params["limit"] = limit
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/slots", params=params)).json()

    async def check(self, doctor_id: uuid.UUID, start: datetime, mode: str) -> dict:
        params = {"start": start.isoformat(), "mode": mode}
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/check", params=params)).json()

    async def interpret_time(self, doctor_id: uuid.UUID, expression: dict, mode: str = "in_person") -> dict:
        return (
            await self.request("POST", f"/internal/v1/doctors/{doctor_id}/interpret-time", params={"mode": mode}, json=expression)
        ).json()

    async def hold(self, doctor_id: uuid.UUID, body: dict) -> dict:
        return (await self.request("POST", f"/internal/v1/doctors/{doctor_id}/holds", json=body)).json()

    async def confirm(self, appointment_id: uuid.UUID, actor: dict) -> dict:
        return (await self.request("POST", f"/internal/v1/appointments/{appointment_id}/confirm", json=actor)).json()

    async def cancel(self, appointment_id: uuid.UUID, actor: dict) -> dict:
        return (await self.request("POST", f"/internal/v1/appointments/{appointment_id}/cancel", json=actor)).json()

    async def no_show(self, appointment_id: uuid.UUID, doctor_id: uuid.UUID) -> dict:
        body = {"doctor_id": str(doctor_id)}
        return (await self.request("POST", f"/internal/v1/appointments/{appointment_id}/no-show", json=body)).json()

    async def notifications(self, patient_id: uuid.UUID, unread_only: bool = False) -> list[dict]:
        params = {"unread_only": str(unread_only).lower()}
        return (await self.request("GET", f"/internal/v1/patients/{patient_id}/notifications", params=params)).json()

    async def read_notification(self, patient_id: uuid.UUID, notification_id: uuid.UUID) -> None:
        await self.request("POST", f"/internal/v1/patients/{patient_id}/notifications/{notification_id}/read")

    async def appointment(
        self, appointment_id: uuid.UUID, *, patient_id: uuid.UUID | None = None, doctor_id: uuid.UUID | None = None
    ) -> dict:
        """One appointment as its patient or its doctor sees it; UpstreamRefusal 404 when it is not theirs."""
        params = {"patient_id": str(patient_id)} if patient_id else {"doctor_id": str(doctor_id)}
        return (await self.request("GET", f"/internal/v1/appointments/{appointment_id}", params=params)).json()

    async def patient_appointments(self, patient_id: uuid.UUID) -> list[dict]:
        return (await self.request("GET", f"/internal/v1/patients/{patient_id}/appointments")).json()

    async def doctor_patient_appointments(self, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> list[dict]:
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/patients/{patient_id}/appointments")).json()

    async def doctor_appointments(self, doctor_id: uuid.UUID, start: datetime, end: datetime) -> list[dict]:
        params = {"start": start.isoformat(), "end": end.isoformat()}
        return (await self.request("GET", f"/internal/v1/doctors/{doctor_id}/appointments", params=params)).json()


_scheduling: SchedulingClient | None = None


def get_scheduling() -> SchedulingClient:
    global _scheduling
    if _scheduling is None:
        _scheduling = SchedulingClient()

    return _scheduling


def set_scheduling(client: SchedulingClient | None) -> None:
    global _scheduling
    _scheduling = client
