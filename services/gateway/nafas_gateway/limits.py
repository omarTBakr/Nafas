"""
Rate limits at the edge: logins, sign-ups, chat messages and voice notes.

Sliding windows kept in this process's memory. With several gateway
replicas each keeps its own count, so a client can get up to N times the
limit; shared limits come with horizontal scaling (docs/CHECKLIST.md,
Phase 9). The client address is the one uvicorn resolved from
X-Forwarded-For, trusted only from FORWARDED_ALLOW_IPS (the web proxy).
"""

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, Request

from nafas_core.clients.identity import Account
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


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def hit(self, limit: Limit, key: str) -> None:
        """Counts one request; Refusal 429 with the wait when the window is full."""
        now = self._clock()
        hits = self._hits[(limit.name, key)]
        while hits and hits[0] <= now - limit.seconds:
            hits.popleft()
        if len(hits) >= limit.count:
            wait = max(1, math.ceil(hits[0] + limit.seconds - now))
            raise Refusal(429, "rate_limited", f"too many requests; try again in {wait} seconds", retry_after=wait)
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_sign_up(request: Request) -> None:
    limiter.hit(SIGN_UP_PER_ADDRESS, client_address(request))


def limit_chat(patient: Account = Depends(current_patient)) -> None:
    limiter.hit(CHAT_PER_PATIENT, str(patient.patient_id))


def limit_voice(patient: Account = Depends(current_patient)) -> None:
    limiter.hit(VOICE_PER_PATIENT, str(patient.patient_id))
