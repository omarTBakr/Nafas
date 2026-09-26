"""The Tavily client: what it sends, what it keeps of the answer, and failing without breaking the chat."""

import json

import httpx
import pytest

import nafas_core.config
from nafas_core.exceptions.providers import SearchError
from nafas_core.interfaces.search import get_web_search, set_web_search
from nafas_core.interfaces.search.tavily import MAX_CONTENT, TavilySearch


async def test_a_search_sends_the_query_and_domains_with_the_key_and_keeps_title_url_and_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "High blood pressure",
                        "url": "https://www.nhs.uk/conditions/high-blood-pressure/",
                        "content": "x" * 5000,
                    },
                    {"title": "", "url": "https://medlineplus.gov/hbp.html", "content": "Lifestyle changes help."},
                    {"title": "no url", "content": "dropped"},
                ]
            },
        )

    search = TavilySearch("tvly-test", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    found = await search.search("what is a normal blood pressure", max_results=3, domains=["nhs.uk", "medlineplus.gov"])

    assert seen["auth"] == "Bearer tvly-test"
    assert seen["body"] == {
        "query": "what is a normal blood pressure",
        "max_results": 3,
        "search_depth": "basic",
        "topic": "general",
        "include_domains": ["nhs.uk", "medlineplus.gov"],
    }
    assert [r.url for r in found] == ["https://www.nhs.uk/conditions/high-blood-pressure/", "https://medlineplus.gov/hbp.html"]
    assert len(found[0].content) == MAX_CONTENT and found[1].title == "https://medlineplus.gov/hbp.html"


@pytest.mark.parametrize("answer", [httpx.Response(401, json={"detail": "bad key"}), httpx.ConnectError("down")])
async def test_a_failed_search_is_a_search_error(answer):
    def handler(request):
        if isinstance(answer, Exception):
            raise answer
        return answer

    with pytest.raises(SearchError):
        await TavilySearch("k", httpx.AsyncClient(transport=httpx.MockTransport(handler))).search("q")


def test_web_search_is_off_without_a_key_and_tavily_with_one(monkeypatch):
    set_web_search(None)
    monkeypatch.setenv("TAVILY_API_KEY", "")
    nafas_core.config._settings_instance = None
    assert get_web_search() is None

    set_web_search(None)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-something")
    nafas_core.config._settings_instance = None
    assert isinstance(get_web_search(), TavilySearch)
    set_web_search(None)
