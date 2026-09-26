"""BookingTools over the scheduling and identity services, for one patient and one doctor."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from nafas_core.clients.identity import IdentityClient
from nafas_core.clients.scheduling import SchedulingClient

TIME_FIELDS = ("start", "end", "hold_expires_at")
ACTIVE = ("held", "confirmed")


class SchedulingTools:
    """
    Acts for exactly one patient with one doctor: the ids are fixed here,
    never taken from the model, so no instruction can book for someone else.
    Every time handed back is in the clinic's zone, as patients say them.
    """

    def __init__(self, scheduling: SchedulingClient, identity: IdentityClient, doctor_id: uuid.UUID, patient_id: uuid.UUID):
        self._scheduling = scheduling
        self._identity = identity
        self._doctor_id = doctor_id
        self._patient_id = patient_id
        self._zone: ZoneInfo | None = None

    async def _clinic_zone(self) -> ZoneInfo:
        if self._zone is None:
            self._zone = ZoneInfo((await self._scheduling.booking_info(self._doctor_id))["timezone"])
        return self._zone

    async def _local(self, record: dict) -> dict:
        """The record with its times converted to clinic time, plus a readable form of the start."""
        zone = await self._clinic_zone()
        out = dict(record)
        for name in TIME_FIELDS:
            if out.get(name):
                out[name] = datetime.fromisoformat(out[name]).astimezone(zone).isoformat()
        if out.get("start"):
            out["start_clinic"] = datetime.fromisoformat(out["start"]).strftime("%A %d %B %Y, %H:%M")
        return out

    async def interpret_time(self, expression: dict) -> dict:
        result = await self._scheduling.interpret_time(self._doctor_id, expression)
        result["candidates"] = [await self._local(c) for c in result["candidates"]]
        result["free_slots"] = [await self._local(s) for s in result["free_slots"]]
        return result

    async def hold(self, start: str, reason_for_visit: str | None) -> dict:
        body = {"patient_id": str(self._patient_id), "start": start, "mode": "in_person", "reason_for_visit": reason_for_visit}
        return await self._local(await self._scheduling.hold(self._doctor_id, body))

    async def confirm(self, appointment_id: str) -> dict:
        confirmed = await self._scheduling.confirm(uuid.UUID(appointment_id), {"patient_id": str(self._patient_id)})
        # the booking puts the patient under the doctor's care, as booking in the UI does
        await self._identity.ensure_care_link(self._doctor_id, self._patient_id)
        return await self._local(confirmed)

    async def cancel(self, appointment_id: str) -> dict:
        return await self._local(await self._scheduling.cancel(uuid.UUID(appointment_id), {"patient_id": str(self._patient_id)}))

    async def my_appointments(self) -> list[dict]:
        mine = await self._scheduling.patient_appointments(self._patient_id)
        return [await self._local(a) for a in mine if a["doctor_id"] == str(self._doctor_id) and a["status"] in ACTIVE]
