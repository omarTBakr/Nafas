"""The speech-to-text port: voice notes, and diarized consultation recordings.

The implementation is the stt GPU service (services/stt), reached over HTTP;
a hosted vendor would be one more module and a factory case.
"""

from nafas_core.interfaces.stt.base import STT, Segment, Transcript
from nafas_core.interfaces.stt.factory import get_stt

__all__ = ["STT", "Segment", "Transcript", "get_stt"]
