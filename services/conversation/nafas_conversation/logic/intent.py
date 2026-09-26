"""
What a patient's message is for.

Two layers, in this order: a keyword check for emergencies, which is plain
code and cannot be talked out of anything; then a small model that sorts
everything else. The keywords only ever add caution: a miss falls through to
the model, which can also say emergency.
"""

import re

from nafas_conversation.enums import Intent
from nafas_conversation.prompts import intent as prompt
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger
from nafas_core.tracing import step

logger = get_logger(__name__)

# the last few turns are enough to read "yes" or "the second one" correctly
CONTEXT_MESSAGES = 6

# Arabic across the dialects, with and without common spelling variants;
# English as written in chats. Matched on normalised text (see _normalise).
EMERGENCY_PATTERNS = [
    # chest pain and heart attack; the intensifiers people actually use
    r"(الم|وجع|وجعني|بيوجعني|يوجعني)\s*((شديد|جامد|جامده|قوي|كتير|بزاف|مره|فظيع)\s*)?(في\s*)?(ال)?صدر",
    r"(ذبح|ازم)(ه|ة)\s*صدري(ه|ة)",
    r"نوب(ه|ة)\s*قلبي(ه|ة)",
    r"chest\s*pain",
    # not "since my heart attack": a past one is history, not an emergency
    r"(?<!since my )(?<!after my )(?<!had a )(?<!my last )heart\s*attack",
    # breathing
    r"(مش\s*قادر|مش\s*عارف|ما\s*اقدر|مقدرش|صعوب(ه|ة)|ضيق)\s*(في\s*)?(ا|ال)?(تنفس|اتنفس|نفس)",
    r"(can'?t|cannot|hard\s*to|trouble|difficulty)\s*breath",
    r"short(ness)?\s*of\s*breath",
    # bleeding, fainting, stroke, seizure
    r"(نزيف|نزف)\s*(شديد|جامد|كتير|مش\s*بيقف)",
    r"(heavy|severe|won'?t\s*stop)\s*bleeding",
    r"(اغمى|اغمي|أغمى|اغماء|فقد(ت)?\s*الوعي)",
    r"(fainted|passed\s*out|unconscious)",
    r"(جلط(ه|ة)|سكت(ه|ة)\s*دماغي(ه|ة))",
    r"stroke",
    r"(تشنج|تشنجات)",
    r"seizure",
    # self-harm
    r"(انتحر|انتحار|[اهحن]?موت\s*نفسي|[اهحن]?قتل\s*نفسي|[اهحن]?اذي\s*نفسي|[اهحن]?أذي\s*نفسي)",
    r"(kill\s*myself|suicid|end\s*my\s*life|hurt\s*myself|self[\s-]*harm)",
]
_EMERGENCY = [re.compile(p) for p in EMERGENCY_PATTERNS]

_ARABIC_DIACRITICS = re.compile(r"[ً-ْـ]")


def _normalise(text: str) -> str:
    """Lower case, no diacritics or tatweel, and one spelling for alef."""
    text = _ARABIC_DIACRITICS.sub("", text.lower())
    return re.sub("[أإآ]", "ا", text)


def looks_like_emergency(text: str) -> bool:
    normalised = _normalise(text)
    return any(pattern.search(normalised) for pattern in _EMERGENCY)


def _transcript(history: list[dict]) -> str:
    speaker = {"user": "Patient", "assistant": "Assistant"}
    return "\n".join(f"{speaker[m['role']]}: {m['content']}" for m in history[-CONTEXT_MESSAGES:])


@step("conversation.intent")
async def classify_intent(llm: LLM, model: str, history: list[dict]) -> Intent | None:
    """The model's reading of the last message; None when it fails, and the caller decides the default."""
    try:
        response = await llm.create(
            model=model,
            system=prompt.SYSTEM,
            tools=[prompt.TOOL],
            tool_choice={"type": "tool", "name": prompt.TOOL["name"]},
            messages=[{"role": "user", "content": _transcript(history)}],
            max_tokens=64,
        )
    except LLMError as exc:
        logger.error("intent classifier failed: %s", exc)
        return None

    for block in response.content:
        if block.type == "tool_use" and block.name == prompt.TOOL["name"]:
            try:
                return Intent(block.input.get("intent"))
            except ValueError:
                break
    logger.warning("intent classifier gave no usable intent")
    return None
