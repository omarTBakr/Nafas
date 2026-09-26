"""The identity service's internal API: reached by other services only, behind the internal token."""

import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from nafas_core.db import session_scope
from nafas_core.enums.identity import UserRole
from nafas_core.internal_api import require_internal_token
from nafas_identity.logic.accounts import AuthenticatedUser, authenticate, get_user


class Credentials(BaseModel):
    email: str
    password: str


class Account(BaseModel):
    user_id: uuid.UUID
    email: str
    role: UserRole
    doctor_id: uuid.UUID | None


def _account(user: AuthenticatedUser) -> Account:
    return Account(user_id=user.user_id, email=user.email, role=user.role, doctor_id=user.doctor_id)


router = APIRouter(prefix="/internal/v1")


@router.post("/auth/verify", response_model=Account)
async def verify_credentials(credentials: Credentials) -> Account:
    """The account for these credentials, or 401 — the same 401 whatever was wrong."""
    async with session_scope() as session:
        user = await authenticate(session, credentials.email, credentials.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    return _account(user)


@router.get("/users/{user_id}", response_model=Account)
async def read_user(user_id: uuid.UUID) -> Account:
    """An active account; 404 when it is gone or disabled, which ends its sessions."""
    async with session_scope() as session:
        user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="no such active account")

    return _account(user)


app = FastAPI(title="Nafas identity (internal)")
# on the router's inclusion, so an endpoint added later is covered by being added at all
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
