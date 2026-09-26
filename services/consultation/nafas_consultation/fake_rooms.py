"""Rooms for tests: who is speaking, what is being recorded, what the room was told."""

import itertools

from nafas_consultation.rooms import RoomEvent, Track


class FakeRooms:
    url = "wss://rooms.test"

    def __init__(self):
        self.tracks: dict[str, list[Track]] = {}
        self.recording: dict[str, tuple[str, str, str]] = {}  # egress id: (room, track, key)
        self.stopped: list[str] = []
        self.announced: list[tuple[str, dict]] = []
        self._ids = (f"EG_{n}" for n in itertools.count(1))

    def join_token(self, room: str, identity: str, name: str) -> str:
        return f"token:{room}:{identity}:{name}"

    async def audio_tracks(self, room: str) -> list[Track]:
        return list(self.tracks.get(room, []))

    async def record_track(self, room: str, track_sid: str, key: str) -> str:
        egress_id = next(self._ids)
        self.recording[egress_id] = (room, track_sid, key)
        return egress_id

    async def stop_recording(self, egress_id: str) -> None:
        self.stopped.append(egress_id)

    async def announce(self, room: str, metadata: dict) -> None:
        self.announced.append((room, metadata))

    def read_webhook(self, body: str, authorization: str) -> RoomEvent:
        if authorization != "signed":
            raise ValueError("not a LiveKit webhook")
        import json

        return RoomEvent(**json.loads(body))
