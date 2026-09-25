"""The dialect identification port, served by the dialect-router service.

Its output is metadata — analytics, reply tone, TTS voice choice — and never
an input to a safety or clinical decision (docs/PLAN.md §1).
"""

from nafas_core.interfaces.dialect.base import DialectClassifier, DialectPrediction
from nafas_core.interfaces.dialect.factory import get_dialect_classifier

__all__ = ["DialectClassifier", "DialectPrediction", "get_dialect_classifier"]
