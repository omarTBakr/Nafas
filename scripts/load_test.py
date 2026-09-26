"""
A load test against a running gateway, checked against the SLOs in
docs/operations/slo.md: `make load-test` or
`uv run python -m scripts.load_test --base http://localhost:8000 --users 50 --seconds 60`.

Simulated patients sign up once, then loop over what patients do most:
browse doctors, look at free slots, read their appointments and notices,
and (with --chat) send a chat message. Chat calls the real model and costs
tokens, so it is off unless asked for, and in staging it runs against the
scripted model. Each request's latency is kept per route; the run fails
(exit 1) when a route misses its latency objective or errors exceed the
budget, so it can gate a promotion.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

# p95 objectives in seconds, and the error budget, from docs/operations/slo.md
# sign-up and login spend most of their time hashing a password, on purpose
OBJECTIVES = {"read": 1.0, "auth": 2.0, "chat": 12.0}
ERROR_BUDGET = 0.005


@dataclass
class Results:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, route: str, seconds: float, ok: bool) -> None:
        self.latencies[route].append(seconds)
        if not ok:
            self.errors[route] += 1


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


async def timed(
    client: httpx.AsyncClient, results: Results, route: str, method: str, url: str, **kwargs
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError:
        results.record(route, time.perf_counter() - started, False)
        return None
    # a 429 is the limiter doing its job, not a failure of the service
    results.record(route, time.perf_counter() - started, response.status_code < 500)
    return response


async def patient(base: str, deadline: float, results: Results, chat: bool, doctor_ids: list[str]) -> None:
    # an address of its own: the gateway honours it only from a proxy it trusts (FORWARDED_ALLOW_IPS),
    # which is how staging runs this, so the per-address sign-up limit sees many people, not one
    address = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={"X-Forwarded-For": address}) as client:
        email = f"load-{uuid.uuid4().hex[:12]}@example.com"
        await timed(
            client,
            results,
            "POST /api/auth/register",
            "POST",
            "/api/auth/register",
            json={"email": email, "password": "load test password 1", "full_name": "Load", "accept_data_processing": True},
        )
        if chat and doctor_ids:
            await client.post("/api/me/consents", json={"kind": "ai_chat", "doctor_id": doctor_ids[0]})
        while time.monotonic() < deadline:
            doctor = random.choice(doctor_ids) if doctor_ids else None
            await timed(client, results, "GET /api/doctors", "GET", "/api/doctors")
            if doctor:
                start = datetime.now(UTC)
                params = {"start": start.isoformat(), "end": (start + timedelta(days=7)).isoformat()}
                await timed(client, results, "GET /api/doctors/{id}/slots", "GET", f"/api/doctors/{doctor}/slots", params=params)
            await timed(client, results, "GET /api/appointments/mine", "GET", "/api/appointments/mine")
            await timed(client, results, "GET /api/notifications", "GET", "/api/notifications")
            if chat and doctor_ids and random.random() < 0.2:
                await timed(
                    client,
                    results,
                    "POST /api/chat/{id}/messages",
                    "POST",
                    f"/api/chat/{doctor_ids[0]}/messages",
                    json={"text": "العيادة بتفتح إمتى؟"},
                )
            # a person, not a script: a second or two between screens
            await asyncio.sleep(random.uniform(0.5, 2.0))


def report(results: Results, seconds: float) -> tuple[dict, bool]:
    rows, passed = {}, True
    total = sum(len(v) for v in results.latencies.values())
    errors = sum(results.errors.values())
    for route, values in sorted(results.latencies.items()):
        kind = "chat" if "/chat/" in route else "auth" if "/auth/" in route else "read"
        objective = OBJECTIVES[kind]
        p95 = percentile(values, 0.95)
        rows[route] = {
            "requests": len(values),
            "p50_ms": round(statistics.median(values) * 1000),
            "p95_ms": round(p95 * 1000),
            "errors": results.errors.get(route, 0),
            "objective_p95_ms": round(objective * 1000),
            "met": p95 <= objective,
        }
        passed &= p95 <= objective
    error_rate = errors / total if total else 0.0
    passed &= error_rate <= ERROR_BUDGET
    summary = {
        "requests": total,
        "requests_per_second": round(total / seconds, 1),
        "error_rate": round(error_rate, 4),
        "error_budget": ERROR_BUDGET,
        "passed": passed,
        "routes": rows,
    }
    return summary, passed


async def run(base: str, users: int, seconds: int, chat: bool) -> tuple[dict, bool]:
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:
        doctor_ids = [d["doctor_id"] for d in (await client.get("/api/doctors")).json()]
    results = Results()
    deadline = time.monotonic() + seconds
    # users arrive over the first tenth of the run, not all in the same millisecond
    tasks = []
    for _ in range(users):
        tasks.append(asyncio.create_task(patient(base, deadline, results, chat, doctor_ids)))
        await asyncio.sleep(seconds / 10 / max(users, 1))
    await asyncio.gather(*tasks)
    return report(results, seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--chat", action="store_true", help="also send chat messages (calls the model)")
    args = parser.parse_args()
    summary, passed = asyncio.run(run(args.base, args.users, args.seconds, args.chat))
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
