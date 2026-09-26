import subprocess

import numpy as np

SAMPLE_RATE = 16_000


class UnreadableAudio(ValueError):
    """ffmpeg could not decode the upload."""


def decode(data: bytes) -> np.ndarray:
    """
    Any container ffmpeg reads → 16 kHz mono float32, what Whisper hears.

    Decoding here rather than inside the model pipeline gives the true
    duration up front, so an over-long recording is refused before the GPU
    spends anything on it.
    """
    process = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ],
        input=data,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0 or not process.stdout:
        raise UnreadableAudio(process.stderr.decode(errors="replace").strip() or "no audio decoded")

    return np.frombuffer(process.stdout, dtype=np.float32)


def seconds(samples: np.ndarray) -> float:
    return len(samples) / SAMPLE_RATE
