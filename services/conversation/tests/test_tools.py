import uuid

import pytest

from nafas_conversation.logic.tools import SchedulingTools


class FakeScheduling:
    def __init__(self):
        self.held: list[dict] = []

    async def booking_info(self, doctor_id):
        return {"timezone": "Africa/Cairo"}

    async def hold(self, doctor_id, body):
        self.held.append(body)
        return {"appointment_id": "a1", "start": body["start"], "status": "held"}


@pytest.fixture
def tools():
    scheduling = FakeScheduling()
    return SchedulingTools(scheduling, identity=None, doctor_id=uuid.uuid4(), patient_id=uuid.uuid4()), scheduling


@pytest.mark.parametrize(
    "typed",
    [
        "2026-10-01T18:00:00+03:00",  # copied correctly
        "2026-10-01T18:00:00+02:00",  # the offset gemma actually wrote: an hour off in Cairo
        "2026-10-01T18:00:00Z",
        "2026-10-01T18:00:00",
    ],
)
async def test_a_held_time_is_the_clinic_clock_whatever_offset_the_model_wrote(tools, typed):
    booking_tools, scheduling = tools

    await booking_tools.hold(typed, None)

    assert scheduling.held[0]["start"] == "2026-10-01T18:00:00+03:00"


async def test_clinic_time_follows_daylight_saving(tools):
    booking_tools, _ = tools

    # Cairo is UTC+2 again after the last Thursday of October
    assert await booking_tools.as_clinic_time("2026-11-05T18:00:00+03:00") == "2026-11-05T18:00:00+02:00"
