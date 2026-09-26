"""
One patient turn: decide what the message is for, then answer it.

Emergencies get fixed words, first and always. Booking (and the small talk
and clinic questions around it) goes to the booking assistant. Medical
questions get a fixed, safe reply until the gated medical pipeline exists
(phase 4).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from nafas_conversation.enums import EscalationReason, Intent
from nafas_conversation.logic.agent import AgentReply, run_booking_turn
from nafas_conversation.logic.context import PatientContext
from nafas_conversation.logic.intent import classify_intent, looks_like_emergency
from nafas_conversation.logic.medical import answer_medical
from nafas_conversation.logic.tools import SchedulingTools
from nafas_conversation.prompts import booking, replies
from nafas_core.clients.identity import IdentityClient
from nafas_core.clients.scheduling import SchedulingClient
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger

logger = get_logger(__name__)

# not a model: the reply was fixed text, chosen by code
FIXED = "fixed"


@dataclass
class Models:
    chat: str
    classifier: str


@dataclass
class Turn:
    reply: AgentReply
    intent: Intent
    # set when the question goes to the doctor: the workflow opens the escalation
    escalation: EscalationReason | None = None
    safety: dict = field(default_factory=dict)


def booking_system_prompt(doctor: dict, profile: dict, clinic_now: datetime) -> str:
    """The booking prompt for this doctor and patient, in the patient's language."""
    arabic = profile["preferred_language"] != "en"
    return booking.SYSTEM.format(
        doctor_name=doctor["full_name_ar"] if arabic else doctor["full_name_en"],
        specialization=doctor["specialization_ar"] if arabic else doctor["specialization_en"],
        language_instruction=booking.language_instruction(profile["preferred_language"], profile.get("dialect")),
        today=clinic_now.strftime("%A %d %B %Y, %H:%M"),
    )


def fixed(text: str) -> AgentReply:
    return AgentReply(text, FIXED, replies.VERSION)


async def answer_booking(
    llm: LLM,
    identity: IdentityClient,
    scheduling: SchedulingClient,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    profile: dict,
    history: list[dict],
    model: str,
    now: datetime,
) -> AgentReply:
    doctor = await identity.doctor(doctor_id)
    zone = ZoneInfo((await scheduling.booking_info(doctor_id))["timezone"])
    return await run_booking_turn(
        llm,
        SchedulingTools(scheduling, identity, doctor_id, patient_id),
        model=model,
        system=booking_system_prompt(doctor, profile, now.astimezone(zone)),
        tool_definitions=booking.TOOLS,
        prompt_version=booking.PROMPT_VERSION,
        history=history,
        apology=booking.APOLOGIES["en" if profile["preferred_language"] == "en" else "ar"],
    )


async def answer_turn(
    llm: LLM,
    identity: IdentityClient,
    scheduling: SchedulingClient,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    history: list[dict],
    models: Models,
    now: datetime,
    context: PatientContext | None = None,
) -> Turn:
    """
    The answer to the last patient message in `history`, and what it was for.

    Never raises: the agent already turns a model failure into an apology,
    and this does the same for anything around it (a lookup that fails, a
    tool whose service is down), in the patient's language when it is known.
    """
    last = history[-1]["content"] if history else ""
    if not last.strip():
        # a voice note that transcribed to nothing: nothing to classify or answer
        language = "ar"
        try:
            language = (await identity.profile(patient_id))["preferred_language"]
        except Exception:
            logger.exception("profile lookup failed for an unheard voice note; answering in Arabic")
        return Turn(fixed(replies.pick(replies.NOT_HEARD, language)), Intent.UNCLEAR)

    # before anything that can fail: the emergency words do not depend on the profile
    if looks_like_emergency(last):
        language = "ar"
        try:
            language = (await identity.profile(patient_id))["preferred_language"]
        except Exception:
            logger.exception("profile lookup failed during an emergency reply; answering in Arabic")
        # the doctor hears of it too, in their inbox
        return Turn(
            fixed(replies.pick(replies.EMERGENCY, language)),
            Intent.EMERGENCY,
            EscalationReason.EMERGENCY,
            {"emergency": "keywords"},
        )

    apology, intent = booking.APOLOGIES["ar"], Intent.UNCLEAR
    try:
        profile = await identity.profile(patient_id)
        language = profile["preferred_language"]
        apology = booking.APOLOGIES["en" if language == "en" else "ar"]

        # a classifier failure falls back to the booking assistant, which
        # itself declines medical questions and points emergencies to 123
        intent = await classify_intent(llm, models.classifier, history) or Intent.BOOKING
        if intent is Intent.EMERGENCY:
            return Turn(
                fixed(replies.pick(replies.EMERGENCY, language)),
                intent,
                EscalationReason.EMERGENCY,
                {"emergency": "classifier"},
            )
        if intent is Intent.MEDICAL:
            outcome = await answer_medical(
                llm,
                identity,
                scheduling,
                patient_id=patient_id,
                doctor_id=doctor_id,
                profile=profile,
                history=history,
                chat_model=models.chat,
                classifier_model=models.classifier,
                context=context,
            )
            if not outcome.not_medical:
                return Turn(outcome.reply, intent, outcome.escalation, outcome.safety)
            # the scope gate read it as not medical after all: the booking assistant answers
            intent = Intent.ADMIN

        reply = await answer_booking(
            llm,
            identity,
            scheduling,
            patient_id=patient_id,
            doctor_id=doctor_id,
            profile=profile,
            history=history,
            model=models.chat,
            now=now,
        )
        return Turn(reply, intent)
    except Exception:
        logger.exception("turn failed for patient %s with doctor %s", patient_id, doctor_id)
        return Turn(AgentReply(apology, models.chat, booking.PROMPT_VERSION), intent)
