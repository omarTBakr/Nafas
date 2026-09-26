from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from nafas_scheduling.enums import AppointmentMode, AvailabilityMode, Unavailable
from nafas_scheduling.exceptions import SlotUnavailableError
from nafas_scheduling.logic.slots import (
    BookingPolicy,
    Interval,
    Schedule,
    WeeklyHours,
    check_start,
    find_slots,
    suggest_near,
)

CAIRO = ZoneInfo("Africa/Cairo")
WEDNESDAY, THURSDAY, FRIDAY = 2, 3, 4


def cairo(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=CAIRO)


def clinic(**policy) -> Schedule:
    """Wednesday and Thursday, 17:00-21:00, 20-minute slots; Thursdays in person only."""
    return Schedule(
        policy=BookingPolicy(timezone="Africa/Cairo", **policy),
        hours=[
            WeeklyHours(WEDNESDAY, time(17), time(21)),
            WeeklyHours(THURSDAY, time(17), time(21), mode=AvailabilityMode.IN_PERSON),
        ],
    )


# a Monday morning, well before the clinic days that follow
NOW = cairo("2026-10-05 09:00")
IN_PERSON, ONLINE = AppointmentMode.IN_PERSON, AppointmentMode.ONLINE


def test_any_whole_minute_inside_hours_is_bookable():
    """ "To the minute": 17:40 is fine even though the grid would offer 17:20 and 18:00."""
    slot = check_start(clinic(), cairo("2026-10-07 17:40"), NOW, IN_PERSON)

    assert slot == Interval(cairo("2026-10-07 17:40"), cairo("2026-10-07 18:00"))


@pytest.mark.parametrize(
    ("start", "reason"),
    [
        ("2026-10-07 17:40:30", Unavailable.NOT_WHOLE_MINUTE),
        ("2026-10-07 16:59", Unavailable.OUTSIDE_HOURS),
        # 20:50 would end at 21:10, past closing
        ("2026-10-07 20:50", Unavailable.OUTSIDE_HOURS),
        ("2026-10-09 18:00", Unavailable.OUTSIDE_HOURS),
        ("2026-10-05 09:30", Unavailable.TOO_SOON),
        ("2027-01-06 18:00", Unavailable.BEYOND_HORIZON),
    ],
)
def test_each_refusal_says_why(start, reason):
    with pytest.raises(SlotUnavailableError) as refused:
        check_start(clinic(), cairo(start), NOW, IN_PERSON)

    assert refused.value.reason is reason


def test_the_last_slot_may_end_exactly_at_closing():
    assert check_start(clinic(), cairo("2026-10-07 20:40"), NOW, IN_PERSON).end == cairo("2026-10-07 21:00")


def test_an_online_request_on_an_in_person_day_says_so():
    with pytest.raises(SlotUnavailableError) as refused:
        check_start(clinic(), cairo("2026-10-08 18:00"), NOW, ONLINE)

    assert refused.value.reason is Unavailable.WRONG_MODE


def test_overlapping_a_booking_is_taken_but_touching_it_is_not():
    schedule = clinic()
    schedule.booked = [Interval(cairo("2026-10-07 18:00"), cairo("2026-10-07 18:20"))]

    with pytest.raises(SlotUnavailableError) as refused:
        check_start(schedule, cairo("2026-10-07 17:50"), NOW, IN_PERSON)
    assert refused.value.reason is Unavailable.TAKEN

    assert check_start(schedule, cairo("2026-10-07 17:40"), NOW, IN_PERSON)
    assert check_start(schedule, cairo("2026-10-07 18:20"), NOW, IN_PERSON)


def test_the_buffer_keeps_time_free_after_each_appointment():
    schedule = clinic(buffer_minutes=10)
    schedule.booked = [Interval(cairo("2026-10-07 18:00"), cairo("2026-10-07 18:20"))]

    with pytest.raises(SlotUnavailableError):
        check_start(schedule, cairo("2026-10-07 18:25"), NOW, IN_PERSON)
    # nor may a new appointment's own buffer run into the next one
    with pytest.raises(SlotUnavailableError):
        check_start(schedule, cairo("2026-10-07 17:35"), NOW, IN_PERSON)

    assert check_start(schedule, cairo("2026-10-07 18:30"), NOW, IN_PERSON)


def test_time_off_wins_over_opening_hours():
    schedule = clinic()
    schedule.time_off = [Interval(cairo("2026-10-07 00:00"), cairo("2026-10-08 00:00"))]

    with pytest.raises(SlotUnavailableError) as refused:
        check_start(schedule, cairo("2026-10-07 18:00"), NOW, IN_PERSON)

    assert refused.value.reason is Unavailable.TIME_OFF


def test_find_slots_walks_the_grid_and_skips_what_is_taken():
    schedule = clinic()
    schedule.booked = [Interval(cairo("2026-10-07 17:20"), cairo("2026-10-07 17:40"))]

    slots = find_slots(schedule, cairo("2026-10-07 00:00"), cairo("2026-10-08 00:00"), NOW, IN_PERSON)

    starts = [s.start.strftime("%H:%M") for s in slots]
    assert starts[:3] == ["17:00", "17:40", "18:00"]
    assert starts[-1] == "20:40"
    assert len(starts) == 11


def test_find_slots_respects_mode_and_limit():
    week = (cairo("2026-10-05 00:00"), cairo("2026-10-12 00:00"))

    online = find_slots(clinic(), *week, NOW, ONLINE)
    first_two = find_slots(clinic(), *week, NOW, IN_PERSON, limit=2)

    assert {s.start.date() for s in online} == {date(2026, 10, 7)}
    assert [s.start for s in first_two] == [cairo("2026-10-07 17:00"), cairo("2026-10-07 17:20")]


def test_suggestions_are_the_nearest_free_slots():
    schedule = clinic()
    schedule.booked = [Interval(cairo("2026-10-07 18:00"), cairo("2026-10-07 18:20"))]

    near = suggest_near(schedule, cairo("2026-10-07 18:00"), NOW, IN_PERSON, count=3)

    # 17:40 and 18:20 are 20 minutes away; 17:20 and 18:40 tie at 40, and the earlier wins
    assert [s.start.strftime("%H:%M") for s in near] == ["17:20", "17:40", "18:20"]


def test_opening_hours_stay_wall_clock_across_daylight_saving():
    """Cairo moves to UTC+3 on the last Friday of April: 17:00 local is 15:00 UTC before, 14:00 after."""
    schedule = clinic()
    before, after = cairo("2026-04-23 17:00"), cairo("2026-04-30 17:00")
    now = cairo("2026-04-20 09:00")

    assert check_start(schedule, before, now, IN_PERSON).start.astimezone(UTC).hour == 15
    assert check_start(schedule, after, now, IN_PERSON).start.astimezone(UTC).hour == 14
    assert find_slots(schedule, after, after + timedelta(hours=1), now, IN_PERSON)[0].start == after


def test_naive_datetimes_are_a_programming_error():
    with pytest.raises(ValueError):
        check_start(clinic(), datetime(2026, 10, 7, 18), NOW, IN_PERSON)
