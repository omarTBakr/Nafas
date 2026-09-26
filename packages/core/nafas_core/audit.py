"""
The audit trail: who read which patient's clinical data, and when.

Append only; services can write it and nobody but the owner can read it.
Every read of clinical data by a person or by the model records one entry,
in its own short transaction, so an entry survives the request that made it
rolling back. A failure to record is logged and raised: a read that cannot
be audited should not go ahead silently.
"""

import json
import uuid
from enum import StrEnum

from sqlalchemy import text

from nafas_core.db import get_engine


class Actor(StrEnum):
    DOCTOR = "doctor"
    PATIENT = "patient"
    MODEL = "model"
    STAFF = "staff"
    SYSTEM = "system"


_INSERT = text(
    "INSERT INTO audit.audit_log"
    " (service, actor_type, actor_id, action, resource_type, resource_id, patient_id, doctor_id, detail)"
    " VALUES (:service, :actor_type, :actor_id, :action, :resource_type, :resource_id, :patient_id, :doctor_id,"
    " CAST(:detail AS jsonb))"
)


async def record(
    *,
    service: str,
    actor: Actor,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> None:
    """One audit entry. `detail` holds ids and counts, never content: the log must not become a copy of the data."""
    async with get_engine().begin() as connection:
        await connection.execute(
            _INSERT,
            {
                "service": service,
                "actor_type": actor.value,
                "actor_id": actor_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id is not None else None,
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "detail": json.dumps(detail or {}),
            },
        )
