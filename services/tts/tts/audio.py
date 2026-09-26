import io
import wave

import numpy as np


def to_wav(samples: np.ndarray, rate: int) -> bytes:
    """Float samples in [-1, 1] → a 16-bit mono WAV, which every browser plays."""
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()
