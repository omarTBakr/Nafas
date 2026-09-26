"""
A patient's medical question, from gates to answer (docs/PLAN.md §3.3).

Only for a patient under this doctor's care with a confirmed or past visit.
The scope and sensitivity gates decide whether the assistant may answer at
all; the answer is written by the conservative patient-chat prompt with
what the patient may see as context; the output guard reads the draft
before the patient does. Anything a gate stops goes to the doctor, and the
patient is told so in fixed words.
"""

import uuid
from dataclasses import dataclass, field

from nafas_conversation.enums import EscalationReason
from nafas_conversation.logic.agent import AgentReply
from nafas_conversation.logic.context import AppointmentsContext, PatientContext
from nafas_conversation.logic.safety import Scope, output_guard, scope_gate, sensitivity_gate
from nafas_conversation.prompts import booking, patient_chat, replies, safety
from nafas_core.clients.identity import IdentityClient
from nafas_core.clients.scheduling import SchedulingClient
from nafas_core.exceptions.providers import LLMError
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger
from nafas_core.metrics import GATE_VERDICTS
from nafas_core.tracing import step

logger = get_logger(__name__)

MAX_TOKENS = 700
FIXED = "fixed"


@dataclass
class MedicalOutcome:
    reply: AgentReply | None
    escalation: EscalationReason | None = None
    # what each gate said, stored on the reply for review and metrics
    safety: dict = field(default_factory=dict)
    # the question was not medical after all: the caller routes it elsewhere
    not_medical: bool = False


def doctor_name(doctor: dict, language: str) -> str:
    return doctor["full_name_en"] if language == "en" else doctor["full_name_ar"]


def escalated(doctor: dict, language: str, reason: EscalationReason, safety_record: dict) -> MedicalOutcome:
    text = replies.pick(replies.ESCALATED, language).format(doctor=doctor_name(doctor, language))
    return MedicalOutcome(AgentReply(text, FIXED, replies.VERSION), reason, safety_record | {"escalated": reason.value})


@step("conversation.medical")
async def answer_medical(
    llm: LLM,
    identity: IdentityClient,
    scheduling: SchedulingClient,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    profile: dict,
    history: list[dict],
    chat_model: str,
    classifier_model: str,
    context: PatientContext | None = None,
) -> MedicalOutcome:
    language = "en" if profile["preferred_language"] == "en" else "ar"
    doctor = await identity.doctor(doctor_id)
    appointments = AppointmentsContext(scheduling)

    # 1. only for this doctor's own patients who have been, or are going, to see them
    if not (await identity.under_care(patient_id, doctor_id) and await appointments.visits(patient_id, doctor_id)):
        return MedicalOutcome(AgentReply(replies.pick(replies.NEEDS_VISIT, language), FIXED, replies.VERSION))

    scope = await identity.doctor_scope(doctor_id)
    record: dict = {"versions": [safety.SCOPE_VERSION, safety.SENSITIVITY_VERSION, safety.GUARD_VERSION]}

    # 2. scope
    verdict = await scope_gate(llm, classifier_model, scope, history)
    record["scope"] = verdict.value if verdict else None
    GATE_VERDICTS.labels("scope", record["scope"] or "failed").inc()
    if verdict is None:
        return escalated(doctor, language, EscalationReason.UNCLEAR, record)
    if verdict is Scope.NON_MEDICAL:
        return MedicalOutcome(None, safety=record, not_medical=True)
    if verdict is Scope.OUT_OF_SCOPE_MEDICAL:
        return escalated(doctor, language, EscalationReason.OUT_OF_SCOPE_MEDICAL, record)

    # 3. sensitivity
    sensitivity = await sensitivity_gate(llm, classifier_model, scope, history)
    record["sensitivity"] = sensitivity.category
    GATE_VERDICTS.labels("sensitivity", sensitivity.category if sensitivity.sensitive else "general").inc()
    if sensitivity.sensitive:
        return escalated(doctor, language, EscalationReason.SENSITIVE, record)

    # 4. the answer, grounded in what the patient may see
    question = history[-1]["content"]
    facts = await (context or appointments).for_patient(patient_id, doctor_id, question)
    system = patient_chat.SYSTEM.format(
        doctor_name=doctor_name(doctor, language),
        specialization=doctor["specialization_en"] if language == "en" else doctor["specialization_ar"],
        language_instruction=booking.language_instruction(profile["preferred_language"], profile.get("dialect")),
        context="\n".join(f"- {fact}" for fact in facts) or "- nothing beyond this conversation",
    )
    try:
        response = await llm.create(model=chat_model, system=system, messages=history, max_tokens=MAX_TOKENS)
    except LLMError as exc:
        logger.error("medical answer failed at the model: %s", exc)
        return escalated(doctor, language, EscalationReason.UNCLEAR, record)
    draft = "".join(block.text for block in response.content if block.type == "text").strip()

    # 5. the guard reads it before the patient does
    passed = bool(draft) and await output_guard(llm, classifier_model, question, draft)
    record["guard"] = "pass" if passed else "block"
    GATE_VERDICTS.labels("guard", record["guard"]).inc()
    if not passed:
        return escalated(doctor, language, EscalationReason.OUTPUT_GUARD, record)

    reply = AgentReply(
        draft,
        response.model,
        patient_chat.PROMPT_VERSION,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    return MedicalOutcome(reply, safety=record)
