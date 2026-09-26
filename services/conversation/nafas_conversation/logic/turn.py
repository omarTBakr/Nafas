"""One patient turn with the booking assistant: what it knows, then the tool loop."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from nafas_conversation.logic.agent import AgentReply, run_booking_turn
from nafas_conversation.logic.tools import SchedulingTools
from nafas_conversation.prompts import booking
from nafas_core.clients.identity import IdentityClient
from nafas_core.clients.scheduling import SchedulingClient
from nafas_core.interfaces.llm import LLM
from nafas_core.logger import get_logger

logger = get_logger(__name__)


def booking_system_prompt(doctor: dict, profile: dict, clinic_now: datetime) -> str:
    """The booking prompt for this doctor and patient, in the patient's language."""
    arabic = profile["preferred_language"] != "en"
    return booking.SYSTEM.format(
        doctor_name=doctor["full_name_ar"] if arabic else doctor["full_name_en"],
        specialization=doctor["specialization_ar"] if arabic else doctor["specialization_en"],
        language_instruction=booking.language_instruction(profile["preferred_language"], profile.get("dialect")),
        today=clinic_now.strftime("%A %d %B %Y, %H:%M"),
    )


async def answer_booking(
    llm: LLM,
    identity: IdentityClient,
    scheduling: SchedulingClient,
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    history: list[dict],
    model: str,
    now: datetime,
) -> AgentReply:
    """
    The assistant's answer to the last patient message in `history`.

    Never raises: the agent already turns a model failure into an apology,
    and this does the same for anything around it (a lookup that fails, a
    tool whose service is down), in the patient's language when it is known.
    """
    apology = booking.APOLOGIES["ar"]
    try:
        profile = await identity.profile(patient_id)
        apology = booking.APOLOGIES["en" if profile["preferred_language"] == "en" else "ar"]
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
            apology=apology,
        )
    except Exception:
        logger.exception("booking turn failed for patient %s with doctor %s", patient_id, doctor_id)
        return AgentReply(apology, model, booking.PROMPT_VERSION)
