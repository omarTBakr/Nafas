"""
Which dialects the loaded tts model really speaks, and a sample of each to
listen to. `make check-tts`. Reads /health (the service asks the model
itself), then speaks one booking sentence per supported dialect into
tts-samples/<dialect>.wav.
"""

import argparse
import asyncio
from pathlib import Path

import httpx

from nafas_conversation.logic.speech import speakable
from nafas_core.config import get_setting
from nafas_core.interfaces.tts.http import HttpTTS

SAMPLE = "تمام، حجزتلك يوم الأربعاء الساعة ٥:٤٠ م. أكّد خلال ١٠ دقايق."


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tts-url", default=get_setting().tts_url)
    parser.add_argument("--out", type=Path, default=Path("tts-samples"))
    args = parser.parse_args()

    async with httpx.AsyncClient(base_url=args.tts_url, timeout=10) as client:
        health = (await client.get("/health")).json()
    print(f"{health['model_id']}@{health['model_revision'][:12]} on {health['device']}")
    unsupported = [code for code, ok in health["dialects"].items() if not ok]
    print("dialects the model does not know:", ", ".join(unsupported) or "none")

    tts = HttpTTS(args.tts_url)
    args.out.mkdir(exist_ok=True)
    for dialect, ok in health["dialects"].items():
        if not ok:
            continue
        speech = await tts.speak(speakable(SAMPLE, dialect), dialect, "female")
        (args.out / f"{dialect}.wav").write_bytes(speech.audio)
        print(f"{dialect}: {speech.seconds:.1f}s -> {args.out / f'{dialect}.wav'}")


if __name__ == "__main__":
    asyncio.run(main())
