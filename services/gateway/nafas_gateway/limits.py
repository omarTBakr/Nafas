"""
Rate limits at the edge: logins, sign-ups, chat messages and voice notes.

Sliding windows, counted in one of two stores. In memory for a laptop and
the tests; in Postgres (RATE_LIMITS_SHARED=true) when there is more than one
gateway replica, so every replica counts against the same window. Staging and
production refuse to start without the shared store. Keys are hashed before
they are stored: no email or address sits in the table. The client address
is the one uvicorn resolved from X-Forwarded-For, trusted only from
FORWARDED_ALLOW_IPS (the web proxy).
"""

import hashlib
import math
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, Request
from sqlalchemy import text

from nafas_core.clients.identity import Account
from nafas_core.config import get_setting
from nafas_core.db import session_scope
from nafas_gateway.errors import Refusal
from nafas_gateway.sessions import current_patient


@dataclass(frozen=True)
class Limit:
    name: str
    count: int
    seconds: int


# generous for a person, tight for a script
LOGIN_PER_ADDRESS = Limit("login-address", 20, 300)
LOGIN_PER_EMAIL = Limit("login-email", 8, 300)
SIGN_UP_PER_ADDRESS = Limit("sign-up", 5, 3600)
CHAT_PER_PATIENT = Limit("chat", 20, 60)
VOICE_PER_PATIENT = Limit("voice", 10, 60)


class Store(Protocol):
    async def hit(self, limit: Limit, key: str) -> float | None:
        """Counts one request; the seconds to wait instead when the window is full."""
        ...


class MemoryStore:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def hit(self, limit: Limit, key: str) -> float | None:
        now = self._clock()
        hits = self._hits[(limit.name, key)]
        while hits and hits[0] <= now - limit.seconds:
            hits.popleft()
        if len(hits) >= limit.count:
            return hits[0] + limit.seconds - now
        hits.append(now)
        return None

    def reset(self) -> None:
        self._hits.clear()


# the longest window any limit uses: older rows are never read again
KEEP_SECONDS = 3600
_COUNT = text(
    "SELECT count(*), extract(epoch FROM min(hit_at)) FROM edge.rate_hits"
    " WHERE limit_name = :name AND key_hash = :key AND hit_at > now() - make_interval(secs => :seconds)"
)
_RECORD = text("INSERT INTO edge.rate_hits (limit_name, key_hash) VALUES (:name, :key)")
_FORGET = text("DELETE FROM edge.rate_hits WHERE hit_at < now() - make_interval(secs => :keep)")


class PostgresStore:
    """
    One row per counted request. A transaction-scoped advisory lock on the
    (limit, key) pair makes count-then-insert exact across replicas; rows
    older than the longest window are swept now and then.
    """

    async def hit(self, limit: Limit, key: str) -> float | None:
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        async with session_scope() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock))"), {"lock": f"{limit.name}:{key_hash}"})
            count, oldest = (await session.execute(_COUNT, {"name": limit.name, "key": key_hash, "seconds": limit.seconds})).one()
            if count >= limit.count:
                now = (await session.execute(text("SELECT extract(epoch FROM now())"))).scalar_one()
                return float(oldest) + limit.seconds - float(now)
            await session.execute(_RECORD, {"name": limit.name, "key": key_hash})
            if random.random() < 0.01:
                await session.execute(_FORGET, {"keep": KEEP_SECONDS})
        return None


class RateLimiter:
    def __init__(self, store: Store | None = None):
        self._store = store

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = PostgresStore() if get_setting().rate_limits_shared else MemoryStore()
        return self._store

    async def hit(self, limit: Limit, key: str) -> None:
        """Counts one request; Refusal 429 with the wait when the window is full."""
        wait = await self.store.hit(limit, key)
        if wait is not None:
            wait = max(1, math.ceil(wait))
            raise Refusal(429, "rate_limited", f"too many requests; try again in {wait} seconds", retry_after=wait)

    def reset(self) -> None:
        """Empties the memory store and forgets which store to use (the tests' settings change)."""
        if isinstance(self._store, MemoryStore):
            self._store.reset()
        self._store = None


limiter = RateLimiter()


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def limit_sign_up(request: Request) -> None:
    await limiter.hit(SIGN_UP_PER_ADDRESS, client_address(request))


async def limit_chat(patient: Account = Depends(current_patient)) -> None:
    await limiter.hit(CHAT_PER_PATIENT, str(patient.patient_id))


async def limit_voice(patient: Account = Depends(current_patient)) -> None:
    await limiter.hit(VOICE_PER_PATIENT, str(patient.patient_id))
