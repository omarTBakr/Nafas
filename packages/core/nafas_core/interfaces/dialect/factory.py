from nafas_core.config import get_setting
from nafas_core.interfaces.dialect.base import DialectClassifier

_classifier: DialectClassifier | None = None


def get_dialect_classifier() -> DialectClassifier:
    """The process-wide client for the dialect-router at DIALECT_ROUTER_URL."""
    global _classifier
    if _classifier is None:
        from nafas_core.interfaces.dialect.http import HttpDialectClassifier

        _classifier = HttpDialectClassifier(get_setting().dialect_router_url)

    return _classifier


def set_dialect_classifier(classifier: DialectClassifier | None) -> None:
    """Replaces the process-wide client; tests pass a FakeDialectClassifier, and None to reset."""
    global _classifier
    _classifier = classifier
