"""
Dashboard sessions: a signed token in an httpOnly cookie.

The token only says who logged in and until when. Every request also asks
identity whether the account is still active (`current_account`), so
disabling a doctor ends their sessions at once rather than at expiry.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Cookie, Depends, HTTPException

from nafas_core.config import get_setting
from nafas_core.enums.identity import UserRole
from nafas_core.exceptions.config import MissingSettingError
from nafas_gateway.clients.identity import Account, get_identity

COOKIE_NAME = "nafas_session"
ALGORITHM = "HS256"
# refuse to sign with a secret short enough to guess
MIN_SECRET_LENGTH = 32


def signing_secret() -> str:
    secret = get_setting().jwt_secret.get_secret_value()
    if len(secret) < MIN_SECRET_LENGTH:
        raise MissingSettingError(f"JWT_SECRET must be set to at least {MIN_SECRET_LENGTH} characters")

    return secret


def issue_token(account: Account, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(account.user_id),
        "role": account.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=get_setting().jwt_ttl_minutes),
    }
    return jwt.encode(claims, signing_secret(), algorithm=ALGORITHM)


def read_token(token: str) -> uuid.UUID | None:
    """The user id in a valid, unexpired token; None for anything else."""
    try:
        claims = jwt.decode(token, signing_secret(), algorithms=[ALGORITHM], options={"require": ["sub", "exp", "iat"]})
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        return None


async def current_account(nafas_session: str | None = Cookie(default=None)) -> Account:
    """The logged-in, still-active account, or 401. Every dashboard route depends on this."""
    user_id = read_token(nafas_session) if nafas_session else None
    account = await get_identity().get_user(user_id) if user_id else None
    if account is None:
        raise HTTPException(status_code=401, detail="not logged in")

    return account


async def current_patient(account: Account = Depends(current_account)) -> Account:
    """A logged-in patient, or 403 for any other role. Patient routes act only on this patient."""
    if account.role is not UserRole.PATIENT or account.patient_id is None:
        raise HTTPException(status_code=403, detail="for patients only")

    return account


async def current_doctor(account: Account = Depends(current_account)) -> Account:
    """A logged-in doctor, or 403 for any other role. Doctor routes act only on this doctor."""
    if account.role is not UserRole.DOCTOR or account.doctor_id is None:
        raise HTTPException(status_code=403, detail="for doctors only")

    return account
