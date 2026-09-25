"""The speech-to-text port: voice notes, and diarized consultation recordings.

No hosted provider is wired yet; the vendor is chosen by the Arabic dialect
spike (docs/CHECKLIST.md, phase 0) and lands here as one more module.
"""

from interfaces.stt.base import STT, Segment, Transcript
from interfaces.stt.factory import get_stt

__all__ = ["STT", "Segment", "Transcript", "get_stt"]
