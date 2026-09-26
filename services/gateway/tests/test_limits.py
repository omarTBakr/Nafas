import pytest
from sqlalchemy import text

from nafas_core.db import session_scope
from nafas_gateway.errors import Refusal
from nafas_gateway.limits import Limit, MemoryStore, PostgresStore, RateLimiter

from .conftest import browser, sign_up


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def test_a_full_window_refuses_until_its_oldest_hit_ages_out():
    clock = Clock()
    limiter = RateLimiter(MemoryStore(clock))
    limit = Limit("t", 2, 60)
    await limiter.hit(limit, "a")
    clock.now += 10
    await limiter.hit(limit, "a")

    with pytest.raises(Refusal) as refused:
        await limiter.hit(limit, "a")
    assert (refused.value.status_code, refused.value.reason, refused.value.retry_after) == (429, "rate_limited", 50)

    # another key has its own window
    await limiter.hit(limit, "b")
    clock.now += 50
    await limiter.hit(limit, "a")


async def test_replicas_share_one_window_in_postgres_and_keys_are_hashed(database):
    limit = Limit("shared-test", 3, 60)
    # two gateway replicas: two limiters, one database
    first, second = RateLimiter(PostgresStore()), RateLimiter(PostgresStore())
    await first.hit(limit, "sara@example.com")
    await second.hit(limit, "sara@example.com")
    await first.hit(limit, "sara@example.com")

    with pytest.raises(Refusal) as refused:
        await second.hit(limit, "sara@example.com")
    assert 50 <= refused.value.retry_after <= 60
    await second.hit(limit, "omar@example.com")

    async with session_scope() as session:
        keys = (await session.execute(text("SELECT DISTINCT key_hash FROM edge.rate_hits"))).scalars().all()
    assert len(keys) == 2 and not any("@" in k for k in keys)


async def test_login_guessing_is_slowed_per_account(doctor_id):
    async with browser() as guesser:
        answers = [
            (await guesser.post("/api/auth/login", json={"email": "Heart@example.com ", "password": f"guess {i}"})).status_code
            for i in range(10)
        ]
        refused = await guesser.post("/api/auth/login", json={"email": "heart@example.com", "password": "x"})

    assert answers[:8] == [401] * 8 and answers[8:] == [429, 429]
    assert refused.json()["reason"] == "rate_limited" and int(refused.headers["retry-after"]) > 0


async def test_sign_ups_are_limited_per_address(doctor_id):
    async with browser() as bot:
        answers = [(await sign_up(bot, email=f"p{i}@example.com")).status_code for i in range(6)]

    assert answers == [201] * 5 + [429]


async def test_chat_is_limited_per_patient(doctor_id):
    from nafas_gateway.limits import CHAT_PER_PATIENT, limiter

    async with browser() as sara:
        await sign_up(sara)
        me = (await sara.get("/api/auth/me")).json()
        for _ in range(CHAT_PER_PATIENT.count):
            await limiter.hit(CHAT_PER_PATIENT, me["patient_id"])
        refused = await sara.post(f"/api/chat/{doctor_id}/messages", json={"text": "hi"})

    assert refused.status_code == 429
