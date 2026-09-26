"""Text normalisation for scoring transcripts: what should not count as a mistake."""

import re

_DIACRITICS = re.compile(r"[ً-ْٰـ]")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalise(text: str) -> str:
    """Lower case, no diacritics, tatweel or punctuation, and one spelling of alef, ya, ta marbuta and hamza seats."""
    text = _DIACRITICS.sub("", text.lower().translate(_DIGITS))
    text = re.sub("[أإآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    text = _PUNCTUATION.sub(" ", text)
    return " ".join(text.split())


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """(edits, reference words): substitutions, insertions and deletions over normalised words."""
    ref, hyp = normalise(reference).split(), normalise(hypothesis).split()
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1], len(ref)
