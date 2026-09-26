"""
The gates a patient's medical question passes before the assistant may
answer it, and the guard its answer passes before the patient sees it.

Order (docs/PLAN.md §3): emergency (already routed by intent), scope,
sensitivity, answer, output guard. Each model gate fails closed: a gate that
errors or gives no verdict sends the question to the doctor. Plain-code
rules come first where words alone settle it (a dose, stopping a medicine),
and only ever add caution.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from nafas_conversation.logic.intent import _normalise
from nafas_conversation.prompts import safety as prompts
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger

logger = get_logger(__name__)

CONTEXT_MESSAGES = 6

# a dose, an amount, or starting, stopping or changing a medicine: always the doctor's
MEDICATION_PATTERNS = [
    r"(جرع(ه|ة)|جرعات|مجم|ملجم|ملغ|مليجرام|ملي\s*جرام|وحد(ه|ة)\s*انسولين)",
    r"\b(\d+\s*)?(mg|mcg|ml|units?)\b",
    r"\b(dose|dosage|doses)\b",
    r"(اوقف|اقطع|ابطل|اسيب|ازود|اقلل|اغير|اوقّف)\s*(ال)?(دوا|دواء|علاج|حبوب|اقراص|حقن)",
    r"(بطلت|وقفت|قطعت)\s*(ال)?(دوا|دواء|علاج|حبوب)",
    r"\b(stop|quit|double|increase|decrease|reduce|skip|switch|change)\b.{0,20}\b(medicine|medication|meds|pills?|tablets?|insulin|dose)\b",
    r"\b(can|should)\s+i\s+take\b",
    r"(ينفع|اقدر|ممكن)\s*(اخد|اخذ|اشرب)",
]
_MEDICATION = [re.compile(p) for p in MEDICATION_PATTERNS]


def mentions_medication_change(text: str) -> bool:
    normalised = _normalise(text)
    return any(p.search(normalised) for p in _MEDICATION)


class Scope(StrEnum):
    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE_MEDICAL = "out_of_scope_medical"
    NON_MEDICAL = "non_medical"


@dataclass
class Sensitivity:
    sensitive: bool
    category: str


def _transcript(history: list[dict]) -> str:
    speaker = {"user": "Patient", "assistant": "Assistant"}
    return "\n".join(f"{speaker[m['role']]}: {m['content']}" for m in history[-CONTEXT_MESSAGES:])


async def _verdict(llm: LLM, model: str, system: str, tool: dict, content: str) -> dict | None:
    """The gate's one tool call, or None when it failed or answered with anything else."""
    try:
        response = await llm.create(
            model=model,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": content}],
            max_tokens=128,
        )
    except LLMError as exc:
        logger.error("%s gate failed: %s", tool["name"], exc)
        return None
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    logger.warning("%s gate gave no verdict", tool["name"])
    return None


async def scope_gate(llm: LLM, model: str, scope: dict, history: list[dict]) -> Scope | None:
    system = prompts.SCOPE_SYSTEM.format(
        specialization=scope["name_en"],
        scope=scope["scope_description"],
        topics=", ".join(scope.get("in_scope_topics") or []) or "none listed",
    )
    verdict = await _verdict(llm, model, system, prompts.SCOPE_TOOL, _transcript(history))
    try:
        return Scope(verdict["verdict"]) if verdict else None
    except (KeyError, ValueError):
        return None


async def sensitivity_gate(llm: LLM, model: str, scope: dict, history: list[dict]) -> Sensitivity:
    """Sensitive unless the model clearly says general; the medication rule decides first."""
    if mentions_medication_change(history[-1]["content"]):
        return Sensitivity(True, "medication")
    system = prompts.SENSITIVITY_SYSTEM.format(always_escalate="; ".join(scope.get("always_escalate") or []) or "none")
    verdict = await _verdict(llm, model, system, prompts.SENSITIVITY_TOOL, _transcript(history))
    if not verdict or not isinstance(verdict.get("sensitive"), bool):
        return Sensitivity(True, "unclear")
    return Sensitivity(verdict["sensitive"], str(verdict.get("category", "unclear")))


async def output_guard(llm: LLM, model: str, question: str, draft: str) -> bool:
    """True when the draft may be shown; any doubt or failure blocks it."""
    if mentions_medication_change(draft):
        return False
    content = f"Patient's question:\n{question}\n\nDraft reply:\n{draft}"
    verdict = await _verdict(llm, model, prompts.GUARD_SYSTEM, prompts.GUARD_TOOL, content)
    return bool(verdict) and verdict.get("verdict") == "pass"
