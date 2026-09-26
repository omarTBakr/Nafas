"""
A visit's transcript, put together from its recorded parts.

The browser records in parts of about a minute, each transcribed on its own.
Each part's segments are moved by the part's offset, so every line keeps its
time from the start of the visit. There is no speaker separation (PLAN.md
§6c): the summary model tells doctor from patient by what is said, and the
doctor reads the draft before anything is filed.
"""

from nafas_core.interfaces.stt.base import Transcript

# a part with no segment timings is assumed to run until the next part starts
NOMINAL_PART_SECONDS = 60.0


def place(transcript: Transcript, offset_seconds: float, next_offset: float | None = None) -> list[dict]:
    """One part's segments in visit time; the whole text as one segment when the provider gave no timings."""
    if transcript.segments:
        return [
            {
                "start": round(offset_seconds + s.start_seconds, 2),
                "end": round(offset_seconds + s.end_seconds, 2),
                "text": s.text.strip(),
            }
            for s in transcript.segments
            if s.text.strip()
        ]
    text = transcript.text.strip()
    if not text:
        return []
    end = next_offset if next_offset is not None else offset_seconds + NOMINAL_PART_SECONDS
    return [{"start": round(offset_seconds, 2), "end": round(end, 2), "text": text}]


def clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes:02d}:{rest:02d}"


def for_prompt(segments: list[dict]) -> str:
    """What the summary model reads: one timed line per segment."""
    return "\n".join(f"[{clock(s['start'])}] {s['text']}" for s in segments)
