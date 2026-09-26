from dataclasses import dataclass
from typing import Protocol


@dataclass
class WebResult:
    title: str
    url: str
    content: str


class WebSearch(Protocol):
    async def search(self, query: str, *, max_results: int = 5, domains: list[str] | None = None) -> list[WebResult]:
        """Pages matching `query`, from `domains` only when given. Raises SearchError on failure."""
        ...
