from nafas_core.enums.dialect import Dialect
from nafas_core.interfaces.dialect.base import DialectPrediction


class FakeDialectClassifier:
    """Answers every text with one fixed dialect, and records the texts."""

    def __init__(self, dialect: Dialect = Dialect.EGYPTIAN, score: float = 0.9):
        self._dialect = dialect
        self._score = score
        self.calls: list[list[str]] = []

    async def classify(self, texts: list[str]) -> list[DialectPrediction]:
        self.calls.append(texts)
        return [DialectPrediction(self._dialect, self._score, self._score < 0.6, "fake") for _ in texts]
