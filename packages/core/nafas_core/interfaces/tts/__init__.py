"""The text-to-speech port: the tts GPU service, and a fake for tests.

Only ever handed text our own normaliser produced (nafas_conversation's
voice logic): booking and admin messages, numbers and times as words.
"""

from nafas_core.interfaces.tts.base import TTS, SpeechAudio
from nafas_core.interfaces.tts.factory import get_tts, set_tts

__all__ = ["TTS", "SpeechAudio", "get_tts", "set_tts"]
