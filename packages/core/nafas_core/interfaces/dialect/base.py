from dataclasses import dataclass
from typing import Protocol

from nafas_core.enums.dialect import Dialect


@dataclass
class DialectPrediction:
    dialect: Dialect
    score: float
    # below the service's threshold: worth a feedback item, not worth trusting
    low_confidence: bool
    # which model produced it, so a stored prediction stays traceable (PLAN §6b)
    model_revision: str


class DialectClassifier(Protocol):
    async def classify(self, texts: list[str]) -> list[DialectPrediction]:
        """One prediction per text, in order. Raises ProviderError when the service fails."""
        ...
