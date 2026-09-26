from nafas_core.config import get_setting
from nafas_core.interfaces.search.base import WebSearch

_search: WebSearch | None = None
_configured = False


def get_web_search() -> WebSearch | None:
    """Tavily when TAVILY_API_KEY is set; None (web search off) otherwise."""
    global _search, _configured
    if not _configured:
        key = get_setting().tavily_api_key.get_secret_value()
        if key:
            from nafas_core.interfaces.search.tavily import TavilySearch

            _search = TavilySearch(key)
        _configured = True
    return _search


def set_web_search(search: WebSearch | None) -> None:
    global _search, _configured
    _search, _configured = search, search is not None
