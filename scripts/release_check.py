"""
After a deploy, before traffic: is every service up, in the environment we
meant, running the commit we meant? `uv run python -m scripts.release_check
--expect abc1234 --environment staging http://identity:8010 http://gateway:8000 ...`
(from inside the stack's network; `make release-check` names every service).
Exits non-zero on any mismatch, so a promotion stops there.
"""

import argparse
import asyncio
import json

import httpx

SERVICES = {
    "gateway": "http://gateway:8000",
    "identity": "http://identity:8010",
    "doctor-assistant": "http://doctor-assistant:8020",
    "scheduling": "http://scheduling:8030",
    "conversation": "http://conversation:8040",
    "clinical-records": "http://clinical-records:8050",
    "consultation": "http://consultation:8060",
}


def verdict(health: dict | None, expect: str, environment: str) -> str | None:
    """None when the service is fit to take traffic; otherwise why not."""
    if health is None:
        return "did not answer /health"
    if health.get("status") != "ok":
        return f"status {health.get('status')!r}"
    if health.get("version") != expect:
        return f"runs {health.get('version')!r}, not {expect!r}"
    if health.get("environment") != environment:
        return f"thinks it is in {health.get('environment')!r}, not {environment!r}"
    return None


async def check(urls: list[str], expect: str, environment: str) -> dict[str, str | None]:
    async with httpx.AsyncClient(timeout=5) as client:

        async def one(url: str) -> tuple[str, str | None]:
            try:
                response = await client.get(f"{url.rstrip('/')}/health")
                health = response.json() if response.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                health = None
            return url, verdict(health, expect, environment)

        return dict(await asyncio.gather(*(one(u) for u in urls)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--expect", required=True, help="the commit every service must report")
    parser.add_argument("--environment", required=True, choices=["dev", "staging", "prod"])
    parser.add_argument("urls", nargs="*", default=list(SERVICES.values()))
    args = parser.parse_args()
    results = asyncio.run(check(args.urls, args.expect, args.environment))
    print(json.dumps({url: problem or "ok" for url, problem in results.items()}, indent=2))
    raise SystemExit(1 if any(results.values()) else 0)


if __name__ == "__main__":
    main()
