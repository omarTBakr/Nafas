"""
Video rooms for online visits, behind a small interface: LiveKit in
production, a fake in tests.

A room is named for its doctor and appointment (`room_name`), so a webhook
about a room says whose it is without any lookup. Participants are named
`doctor:<id>` and `patient:<id>`, which is how a recorded track knows its
speaker. Recording is track egress: each microphone written as it was sent
(Opus in Ogg), straight to storage, with no transcoding and no headless
browser.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from livekit import api

from nafas_core.config import get_setting

JOIN_TOKEN_TTL = timedelta(hours=2)


def room_name(doctor_id: uuid.UUID, appointment_id: uuid.UUID) -> str:
    return f"visit-{doctor_id}-{appointment_id}"


def parse_room(name: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(doctor_id, appointment_id) from a room's name; None for a room that is not a visit."""
    if not name.startswith("visit-"):
        return None
    rest = name.removeprefix("visit-")
    try:
        return uuid.UUID(rest[:36]), uuid.UUID(rest[37:])
    except ValueError:
        return None


def participant(role: str, person_id: uuid.UUID) -> str:
    return f"{role}:{person_id}"


def speaker_of(identity: str) -> str | None:
    role = identity.split(":", 1)[0]
    return role if role in ("doctor", "patient") else None


@dataclass
class Track:
    identity: str
    track_sid: str


@dataclass
class RoomEvent:
    """What the consultation service needs from a LiveKit webhook."""

    event: str
    room: str
    egress_id: str | None = None
    egress_status: str | None = None
    egress_error: str | None = None
    track_sid: str | None = None
    identity: str | None = None
    audio: bool = False


class Rooms(Protocol):
    @property
    def url(self) -> str: ...

    def join_token(self, room: str, identity: str, name: str) -> str: ...

    async def audio_tracks(self, room: str) -> list[Track]: ...

    async def record_track(self, room: str, track_sid: str, key: str) -> str:
        """Starts writing one track to `key` in storage; the egress id."""
        ...

    async def stop_recording(self, egress_id: str) -> None: ...

    async def announce(self, room: str, metadata: dict) -> None:
        """Room metadata every participant sees change: whether the visit is being recorded."""
        ...

    def read_webhook(self, body: str, authorization: str) -> RoomEvent:
        """A webhook's event, once its signature is checked; ValueError when it is not LiveKit's."""
        ...


class LiveKitRooms:
    def __init__(self):
        settings = get_setting()
        self._url = settings.livekit_url
        self._api_url = settings.livekit_api_url or settings.livekit_url.replace("wss://", "https://").replace("ws://", "http://")
        self._key, self._secret = settings.livekit_api_key, settings.livekit_api_secret.get_secret_value()
        self._s3 = api.S3Upload(
            access_key=settings.s3_access_key.get_secret_value(),
            secret=settings.s3_secret_key.get_secret_value(),
            region=settings.s3_region,
            endpoint=settings.egress_s3_endpoint or settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            force_path_style=True,
        )

    @property
    def url(self) -> str:
        return self._url

    def _api(self) -> api.LiveKitAPI:
        return api.LiveKitAPI(self._api_url, self._key, self._secret)

    def join_token(self, room: str, identity: str, name: str) -> str:
        grants = api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=False)
        return (
            api.AccessToken(self._key, self._secret)
            .with_identity(identity)
            .with_name(name)
            .with_grants(grants)
            .with_ttl(JOIN_TOKEN_TTL)
            .to_jwt()
        )

    async def audio_tracks(self, room: str) -> list[Track]:
        async with self._api() as lk:
            try:
                listed = await lk.room.list_participants(api.ListParticipantsRequest(room=room))
            except api.TwirpError:
                return []
        return [Track(p.identity, t.sid) for p in listed.participants for t in p.tracks if t.type == api.TrackType.AUDIO]

    async def record_track(self, room: str, track_sid: str, key: str) -> str:
        request = api.TrackEgressRequest(
            room_name=room, track_id=track_sid, file=api.DirectFileOutput(filepath=key, s3=self._s3, disable_manifest=True)
        )
        async with self._api() as lk:
            info = await lk.egress.start_track_egress(request)
        return info.egress_id

    async def stop_recording(self, egress_id: str) -> None:
        async with self._api() as lk:
            try:
                await lk.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))
            except api.TwirpError:
                # already ended (the participant left): the webhook says how
                pass

    async def announce(self, room: str, metadata: dict) -> None:
        async with self._api() as lk:
            await lk.room.update_room_metadata(api.UpdateRoomMetadataRequest(room=room, metadata=json.dumps(metadata)))

    def read_webhook(self, body: str, authorization: str) -> RoomEvent:
        try:
            event = api.WebhookReceiver(api.TokenVerifier(self._key, self._secret)).receive(body, authorization)
        except Exception as exc:
            raise ValueError("not a LiveKit webhook") from exc
        egress = event.egress_info if event.HasField("egress_info") else None
        return RoomEvent(
            event=event.event,
            room=event.room.name or (egress.room_name if egress else ""),
            egress_id=egress.egress_id if egress else None,
            egress_status=api.EgressStatus.Name(egress.status) if egress else None,
            egress_error=egress.error if egress and egress.error else None,
            track_sid=event.track.sid if event.HasField("track") else None,
            identity=event.participant.identity if event.HasField("participant") else None,
            audio=event.HasField("track") and event.track.type == api.TrackType.AUDIO,
        )


_rooms: Rooms | None = None


def get_rooms() -> Rooms | None:
    """The rooms, or None when online visits are not set up (no LIVEKIT_URL)."""
    global _rooms
    if _rooms is None and get_setting().livekit_url:
        _rooms = LiveKitRooms()
    return _rooms


def set_rooms(rooms: Rooms | None) -> None:
    global _rooms
    _rooms = rooms
