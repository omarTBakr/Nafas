from nafas_core.interfaces.search.base import WebResult


class FakeWebSearch:
    """Returns fixed results and records every query, so a test can see exactly what left the system."""

    def __init__(self, results: list[WebResult] | None = None, fails: bool = False):
        self._results, self._fails = results or [], fails
        self.queries: list[tuple[str, list[str] | None]] = []

    async def search(self, query: str, *, max_results: int = 5, domains: list[str] | None = None) -> list[WebResult]:
        from nafas_core.exceptions.providers import SearchError

        self.queries.append((query, domains))
        if self._fails:
            raise SearchError("search is down")
        return self._results[:max_results]
