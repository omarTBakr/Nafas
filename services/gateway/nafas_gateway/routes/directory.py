import uuid

from fastapi import APIRouter

from nafas_gateway.clients.identity import get_identity

# public: choosing a doctor comes before signing up, and none of this is patient data
router = APIRouter(prefix="/api", tags=["directory"])


@router.get("/specializations")
async def specializations() -> list[dict]:
    return await get_identity().specializations()


@router.get("/doctors")
async def doctors(specialization: str | None = None) -> list[dict]:
    return await get_identity().doctors(specialization)


@router.get("/doctors/{doctor_id}")
async def doctor(doctor_id: uuid.UUID) -> dict:
    return await get_identity().doctor(doctor_id)
