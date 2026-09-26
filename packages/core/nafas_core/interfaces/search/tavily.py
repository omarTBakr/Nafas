"""Web search through Tavily's API (https://api.tavily.com/search), for grounding answers in published sources."""

import httpx

from nafas_core.exceptions.providers import SearchError
from nafas_core.interfaces.search.base import WebResult

ENDPOINT = "https://api.tavily.com/search"
TIMEOUT_SECONDS = 15.0
# a passage long enough to answer from, short enough to keep the prompt small
MAX_CONTENT = 1200


class TavilySearch:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)

    async def search(self, query: str, *, max_results: int = 5, domains: list[str] | None = None) -> list[WebResult]:
        body = {"query": query, "max_results": max_results, "search_depth": "basic", "topic": "general"}
        if domains:
            body["include_domains"] = domains
        try:
            response = await self._client.post(ENDPOINT, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise SearchError(f"web search unreachable: {exc}") from exc
        if response.status_code != 200:
            raise SearchError(f"web search answered {response.status_code}")
        return [
            WebResult(title=r.get("title") or r["url"], url=r["url"], content=(r.get("content") or "")[:MAX_CONTENT])
            for r in response.json().get("results", [])
            if r.get("url")
        ]
