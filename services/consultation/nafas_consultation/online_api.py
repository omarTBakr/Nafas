"""
Online visits' API: joining a room, recording it, and LiveKit's webhooks.

Joining and recording are internal calls from the gateway, behind the
internal token. The webhook comes from LiveKit itself and is checked by its
signature instead (a JWT over the body's SHA-256, signed with the LiveKit
secret), so nothing else can claim a track was written.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from nafas_consultation.enums import ConsultationStatus
from nafas_consultation.exceptions import JoinRefusedError, NotUnderCareError, WrongStateError
from nafas_consultation.logic import consultations, online
from nafas_consultation.rooms import Rooms, Track, get_rooms, parse_room, participant, room_name
from nafas_core import audit
from nafas_core.clients.base import UpstreamRefusal
from nafas_core.clients.identity import get_identity
from nafas_core.clients.scheduling import get_scheduling
from nafas_core.db import session_scope
from nafas_core.internal_api import require_internal_token
from nafas_core.logger import get_logger

logger = get_logger(__name__)


class JoinIn(BaseModel):
    role: Literal["doctor", "patient"]
    person_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)


class RecordingIn(BaseModel):
    evidence: str = Field(default="verbal, at the start of the online visit", min_length=1, max_length=200)


def _rooms() -> Rooms:
    rooms = get_rooms()
    if rooms is None:
        raise JoinRefusedError("online_visits_off")
    return rooms


async def _appointment(appointment_id: uuid.UUID, role: str, person_id: uuid.UUID) -> dict:
    """The appointment as this person sees it; 404 when it is not theirs."""
    scope = {"patient_id": person_id} if role == "patient" else {"doctor_id": person_id}
    try:
        return await get_scheduling().appointment(appointment_id, **scope)
    except UpstreamRefusal as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="no such appointment") from exc
        raise


def _joinable(appointment: dict) -> None:
    refusal = online.join_refusal(appointment, datetime.now(UTC))
    if refusal:
        raise JoinRefusedError(refusal)


router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_internal_token)])


@router.post("/appointments/{appointment_id}/join")
async def join(appointment_id: uuid.UUID, body: JoinIn) -> dict:
    """A token for this appointment's room, for its patient or its doctor, within the visit's window."""
    rooms = _rooms()
    appointment = await _appointment(appointment_id, body.role, body.person_id)
    _joinable(appointment)
    room = room_name(uuid.UUID(appointment["doctor_id"]), appointment_id)
    await audit.record(
        service="consultation",
        actor=audit.Actor.DOCTOR if body.role == "doctor" else audit.Actor.PATIENT,
        actor_id=body.person_id,
        action="join_visit",
        resource_type="appointment",
        resource_id=appointment_id,
        patient_id=uuid.UUID(appointment["patient_id"]),
        doctor_id=uuid.UUID(appointment["doctor_id"]),
    )
    return {
        "url": rooms.url,
        "room": room,
        "token": rooms.join_token(room, participant(body.role, body.person_id), body.name),
        "role": body.role,
        "appointment": appointment,
    }


async def _record(rooms: Rooms, consultation, track: Track, now: datetime) -> None:
    """Starts writing one participant's microphone into this visit."""
    if any(p.get("track_sid") == track.track_sid for p in consultation.parts):
        return
    part = online.new_part(consultation, track, egress_id="", now=now)
    part["egress_id"] = await rooms.record_track(consultation.room, track.track_sid, part["key"])
    consultation.parts = [*consultation.parts, part]


@router.post("/doctors/{doctor_id}/appointments/{appointment_id}/recording", status_code=201)
async def start_recording(doctor_id: uuid.UUID, appointment_id: uuid.UUID, body: RecordingIn) -> dict:
    """The patient agreed, in the call: record each participant's microphone from now on."""
    rooms = _rooms()
    appointment = await _appointment(appointment_id, "doctor", doctor_id)
    _joinable(appointment)
    patient_id, room = uuid.UUID(appointment["patient_id"]), room_name(doctor_id, appointment_id)
    async with session_scope(doctor_id=doctor_id) as session:
        if await online.recording_in(session, room):
            raise WrongStateError("this visit is already being recorded")
    try:
        consent = await get_identity().record_recording_consent(doctor_id, patient_id, body.evidence)
    except UpstreamRefusal as exc:
        if exc.status_code == 409:
            raise NotUnderCareError(f"{patient_id} is not under {doctor_id}'s care") from exc
        raise

    now = datetime.now(UTC)
    tracks = await rooms.audio_tracks(room)
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.create(
            session,
            doctor_id=doctor_id,
            patient_id=patient_id,
            consent_id=uuid.UUID(consent["consent_id"]),
            appointment_id=appointment_id,
        )
        consultation.source, consultation.room, consultation.started_at = "online", room, now
        for track in tracks:
            await _record(rooms, consultation, track, now)
        await audit.record(
            service="consultation",
            actor=audit.Actor.DOCTOR,
            actor_id=doctor_id,
            action="start_recording",
            resource_type="consultation",
            resource_id=consultation.id,
            patient_id=patient_id,
            doctor_id=doctor_id,
            detail={"consent_id": consent["consent_id"], "tracks": len(tracks), "source": "online"},
        )
        consultation_id = consultation.id
    # everyone in the room sees it is being recorded
    await rooms.announce(room, {"recording": True, "consultation_id": str(consultation_id)})
    return {"consultation_id": str(consultation_id), "tracks": len(tracks)}


async def _stop(rooms: Rooms, doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> dict:
    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        if consultation.source != "online":
            raise WrongStateError("only an online visit is stopped this way")
        consultations.require(consultation, ConsultationStatus.RECORDING)
        if consultation.recording_stopped_at is None:
            consultation.recording_stopped_at = datetime.now(UTC)
        room, writing = consultation.room, [p["egress_id"] for p in consultation.parts if p.get("state") == "recording"]
    for egress_id in writing:
        await rooms.stop_recording(egress_id)
    await rooms.announce(room, {"recording": False})
    return await _process_if_written(doctor_id, consultation_id)


async def _process_if_written(doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> dict:
    """Once the doctor has stopped and every track's file is written, the visit goes to its workflow."""
    from nafas_consultation.api import begin_processing

    async with session_scope(doctor_id=doctor_id) as session:
        consultation = await consultations.get(session, consultation_id)
        stopped = consultation.recording_stopped_at is not None
        waiting = online.still_writing(consultation)
        written = [p for p in consultation.parts if p.get("state") == "written"]
        if stopped and not waiting and not written and consultation.status is ConsultationStatus.RECORDING:
            consultations.mark(consultation, ConsultationStatus.FAILED, "nothing was recorded: no microphone in the room")
        status = consultation.status
    if stopped and not waiting and written and status is ConsultationStatus.RECORDING:
        status = (await begin_processing(doctor_id, consultation_id)).status
    return {"consultation_id": str(consultation_id), "status": status.value, "waiting_for_tracks": waiting}


@router.post("/doctors/{doctor_id}/consultations/{consultation_id}/stop-recording")
async def stop_recording(doctor_id: uuid.UUID, consultation_id: uuid.UUID) -> dict:
    """The doctor stopped: every track stops; the visit is processed when their files are written."""
    return await _stop(_rooms(), doctor_id, consultation_id)


webhooks = APIRouter()


@webhooks.post("/webhooks/livekit", status_code=204)
async def livekit_webhook(request: Request) -> None:
    """
    LiveKit tells us about rooms: a microphone published while recording is
    recorded too; a track's file written (or not) is marked; a room that
    finished while recording stops it.
    """
    rooms = _rooms()
    body = (await request.body()).decode()
    try:
        event = rooms.read_webhook(body, request.headers.get("Authorization", ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="not signed by LiveKit") from exc
    owner = parse_room(event.room)
    if owner is None:
        return
    doctor_id, _ = owner

    if event.event == "track_published" and event.audio and event.track_sid and event.identity:
        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await online.recording_in(session, event.room)
            if consultation is not None and consultation.recording_stopped_at is None:
                await _record(rooms, consultation, Track(event.identity, event.track_sid), datetime.now(UTC))
    elif event.event == "egress_ended" and event.egress_id:
        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await online.recording_in(session, event.room)
            found = consultation is not None and online.mark_part(consultation, event.egress_id, event.egress_status or "")
            consultation_id = consultation.id if consultation is not None else None
        if event.egress_error:
            logger.warning("a track of %s was not written: %s", consultation_id, event.egress_error)
        if found:
            await _process_if_written(doctor_id, consultation_id)
    elif event.event == "room_finished":
        async with session_scope(doctor_id=doctor_id) as session:
            consultation = await online.recording_in(session, event.room)
            consultation_id = consultation.id if consultation is not None else None
        if consultation_id is not None:
            await _stop(rooms, doctor_id, consultation_id)
