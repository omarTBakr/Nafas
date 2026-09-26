"""
The doctor assistant's internal API: one streamed chat turn, as server-sent
events. The gateway forwards the doctor's request and the stream back; the
doctor and the selected patient come from the gateway's session, never from
the model.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from nafas_core.clients.clinical import get_clinical
from nafas_core.clients.conversation import get_conversation
from nafas_core.clients.identity import get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.config import get_setting
from nafas_core.health import health_info
from nafas_core.interfaces.llm import get_llm
from nafas_core.interfaces.search import get_web_search
from nafas_core.internal_api import require_internal_token
from nafas_core.metrics import instrument
from nafas_doctor_assistant.logic.chat import run_doctor_chat
from nafas_doctor_assistant.logic.tools import DoctorTools
from nafas_doctor_assistant.prompts import doctor_chat

# how much of the conversation the model sees; the dashboard keeps the rest
HISTORY_LIMIT = 30


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatIn(BaseModel):
    patient_id: uuid.UUID | None = None
    messages: list[Turn] = Field(min_length=1)


def sse(event: dict) -> bytes:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


router = APIRouter(prefix="/internal/v1")


@router.post("/doctors/{doctor_id}/chat")
async def chat(doctor_id: uuid.UUID, body: ChatIn):
    identity = get_identity()
    patient = None
    if body.patient_id is not None:
        patient = next((p for p in await identity.roster(doctor_id) if p["patient_id"] == str(body.patient_id)), None)
        if patient is None:
            return JSONResponse(
                status_code=409, content={"detail": "this patient is not under your care", "reason": "not_under_care"}
            )
    if body.messages[-1].role != "user":
        return JSONResponse(status_code=422, content={"detail": "the last message must be the doctor's"})

    doctor = await identity.doctor(doctor_id)
    timezone = (await get_scheduling().booking_info(doctor_id))["timezone"]
    web = get_web_search() if get_setting().web_search_doctor else None
    tools = DoctorTools(
        doctor_id=doctor_id,
        patient_id=body.patient_id,
        timezone=timezone,
        identity=identity,
        scheduling=get_scheduling(),
        clinical=get_clinical(),
        conversation=get_conversation(),
        web=web,
    )
    patient_line = (
        doctor_chat.PATIENT.format(name=patient["full_name"], patient_id=patient["patient_id"])
        if patient
        else doctor_chat.NO_PATIENT
    )
    system = doctor_chat.SYSTEM.format(
        doctor_name=doctor["full_name_en"],
        specialization=doctor["specialization_en"],
        patient_line=patient_line,
        web_line=doctor_chat.WEB if web else doctor_chat.NO_WEB,
        timezone=timezone,
        now=datetime.now(UTC).astimezone(ZoneInfo(timezone)).strftime("%A %d %B %Y, %H:%M"),
    )
    history = [{"role": t.role, "content": t.content} for t in body.messages[-HISTORY_LIMIT:]]

    async def events():
        async for event in run_doctor_chat(
            get_llm(),
            tools,
            model=get_setting().llm_chat_model,
            system=system,
            tool_definitions=doctor_chat.tools(web is not None),
            prompt_version=doctor_chat.PROMPT_VERSION,
            history=history,
        ):
            yield sse(event)

    # no buffering by a proxy between here and the browser
    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


app = FastAPI(title="Nafas doctor assistant (internal)")
instrument(app, "doctor-assistant")
app.include_router(router, dependencies=[Depends(require_internal_token)])


@app.get("/health")
async def health() -> dict:
    return health_info("doctor-assistant", **{"prompts": {"doctor_chat": doctor_chat.PROMPT_VERSION}})
