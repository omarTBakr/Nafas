"""Text into passages small enough to embed well and quote back, split where sentences end."""

import re

MAX_CHARS = 900
OVERLAP_CHARS = 150

# a sentence or line ends: Latin and Arabic stops, question and exclamation marks, line breaks
_BREAK = re.compile(r"(?<=[.!?؟۔])\s+|\n+")


def split_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """
    Passages of at most `max_chars`, each starting with the tail of the one
    before so a fact that straddles a boundary is still found whole. A
    sentence longer than a passage is cut by words.
    """
    sentences = [s.strip() for s in _BREAK.split(text) if s and s.strip()]
    pieces: list[str] = []
    for sentence in sentences:
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)

    passages: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > max_chars:
            passages.append(current)
            tail = current[-overlap:]
            tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
            current = f"{tail} {piece}" if overlap and len(tail) + 1 + len(piece) <= max_chars else piece
        else:
            current = f"{current} {piece}" if current else piece
    if current:
        passages.append(current)
    return passages
