"""
Word error rate of the stt service on our own labelled clips, per dialect,
beside the model card's published figures. `make check-stt CLIPS=path/to/clips`.

The clips directory holds audio files and a manifest.csv with columns
file, dialect (eg, sa, ... or en), reference (what was said), and optionally
seconds (the clip's length; else the last segment's end). English clips
answer the Phase 3 question: did the fine-tune keep English? The report also
gives the real-time factor, which sizes the GPU for recorded visits. Writes
report.md next to the manifest; audio and text stay on this machine.
"""

import argparse
import asyncio
import csv
import mimetypes
import time
from collections import defaultdict
from pathlib import Path

from nafas_core.config import get_setting
from nafas_core.interfaces.stt.http import HttpSTT
from scripts.checks.arabic import word_errors

# oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2, as recorded in docs/PLAN.md
PUBLISHED_WER = {"all": 0.332, "sa": 0.17, "iq": 0.27, "eg": 0.27, "sy": 0.27, "tn": 0.48}
# a dialect this much worse than published is a finding, not noise
TOLERANCE = 0.05
# proposed, not from any card: English worse than this sends English patients to base turbo
ENGLISH_FALLBACK_WER = 0.15


def report(rows: list[dict]) -> str:
    by_dialect: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        stats = by_dialect[row["dialect"]]
        stats[0] += row["edits"]
        stats[1] += row["words"]
        stats[2] += 1
    total_edits = sum(s[0] for s in by_dialect.values())
    total_words = sum(s[1] for s in by_dialect.values())

    lines = ["| dialect | clips | WER | published | verdict |", "| --- | --- | --- | --- | --- |"]
    for dialect, (edits, words, clips) in sorted(by_dialect.items()):
        wer = edits / words if words else 0.0
        published = PUBLISHED_WER.get(dialect)
        if published is None:
            verdict = "no published figure"
        else:
            verdict = "worse than published" if wer > published + TOLERANCE else "as published or better"
        shown = f"{published:.3f}" if published is not None else "n/a"
        lines.append(f"| {dialect} | {clips} | {wer:.3f} | {shown} | {verdict} |")
    overall = total_edits / total_words if total_words else 0.0
    lines.append(f"| all | {len(rows)} | {overall:.3f} | {PUBLISHED_WER['all']:.3f} | |")
    timed = [r for r in rows if r.get("audio_seconds")]
    if timed:
        audio = sum(r["audio_seconds"] for r in timed)
        took = sum(r["took_seconds"] for r in timed)
        factor = took / audio
        lines += [
            "",
            f"Speed: {audio:.0f} s of audio in {took:.1f} s, real-time factor {factor:.3f}. "
            f"A 20-minute visit would take about {20 * 60 * factor:.0f} s to transcribe "
            "(objective: the draft within 300 s, docs/operations/slo.md).",
        ]
    if "en" in by_dialect:
        edits, words, _ = by_dialect["en"]
        wer = edits / words
        decision = "fall back to base turbo for English patients" if wer > ENGLISH_FALLBACK_WER else "keep the fine-tune"
        lines += ["", f"English WER {wer:.3f} (proposed bar {ENGLISH_FALLBACK_WER}): {decision}."]
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clips", type=Path)
    parser.add_argument("--stt-url", default=get_setting().stt_url)
    args = parser.parse_args()

    stt = HttpSTT(args.stt_url)
    rows = []
    with (args.clips / "manifest.csv").open(encoding="utf-8") as manifest:
        for entry in csv.DictReader(manifest):
            audio = (args.clips / entry["file"]).read_bytes()
            mime = mimetypes.guess_type(entry["file"])[0] or "audio/wav"
            language = "en" if entry["dialect"] == "en" else "ar"
            started = time.perf_counter()
            transcript = await stt.transcribe(audio, mime, language_hint=language)
            took = time.perf_counter() - started
            edits, words = word_errors(entry["reference"], transcript.text)
            # the clip's length: from the manifest when given, else where the last segment ends
            seconds = float(entry.get("seconds") or 0) or max((s.end_seconds for s in transcript.segments), default=0.0)
            rows.append(
                {"dialect": entry["dialect"], "edits": edits, "words": words, "audio_seconds": seconds, "took_seconds": took}
            )
            print(f"{entry['file']}: {edits}/{words}")

    out = args.clips / "report.md"
    out.write_text(report(rows), encoding="utf-8")
    print(f"\n{out}\n{out.read_text(encoding='utf-8')}")


if __name__ == "__main__":
    asyncio.run(main())
