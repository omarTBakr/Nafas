"""
Dashboard sessions: a signed token in an httpOnly cookie.

The token only says who logged in and until when. Every request also asks
identity whether the account is still active (`current_account`), so
disabling a doctor ends their sessions at once rather than at expiry.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Cookie, Depends, HTTPException

from nafas_core.clients.identity import Account, get_identity
from nafas_core.config import get_setting
from nafas_core.enums.identity import UserRole
from nafas_core.exceptions.config import MissingSettingError

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


class AccountCache:
    """
    Recently confirmed accounts, so a burst of requests from one browser asks
    identity once, not once per request (identity was the busiest service in
    the load test, docs/operations/capacity.md). The price: an account
    disabled in identity keeps working for up to SESSION_CHECK_SECONDS here.
    """

    def __init__(self, clock=time.monotonic, max_entries: int = 50_000):
        self._clock, self._max = clock, max_entries
        self._entries: dict[uuid.UUID, tuple[float, Account]] = {}

    def get(self, user_id: uuid.UUID) -> Account | None:
        entry = self._entries.get(user_id)
        if entry is None or entry[0] <= self._clock():
            self._entries.pop(user_id, None)
            return None
        return entry[1]

    def put(self, user_id: uuid.UUID, account: Account, seconds: float) -> None:
        if len(self._entries) >= self._max:
            # full: drop what has expired, and if that is not enough, start over
            now = self._clock()
            self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
            if len(self._entries) >= self._max:
                self._entries.clear()
        self._entries[user_id] = (self._clock() + seconds, account)

    def clear(self) -> None:
        self._entries.clear()


accounts = AccountCache()


async def current_account(nafas_session: str | None = Cookie(default=None)) -> Account:
    """The logged-in, still-active account, or 401. Every dashboard route depends on this."""
    user_id = read_token(nafas_session) if nafas_session else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="not logged in")
    account = accounts.get(user_id)
    if account is None:
        account = await get_identity().get_user(user_id)
        if account is None:
            raise HTTPException(status_code=401, detail="not logged in")
        if (seconds := get_setting().session_check_seconds) > 0:
            accounts.put(user_id, account, seconds)

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
