"""
When a doctor can be booked, as pure functions over a Schedule.

Times are timezone-aware datetimes throughout. Weekly hours are wall-clock
times in the doctor's zone, so a clinic that opens at 17:00 opens at 17:00
local on both sides of a daylight-saving change, whatever that is in UTC.

A patient may ask for any whole minute (17:40, not only the 20-minute grid):
`check_start` validates exactly that minute. The grid is only how
`find_slots` and `suggest_near` offer times when the patient has none in mind.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nafas_scheduling.enums import AppointmentMode, AvailabilityMode, Unavailable
from nafas_scheduling.exceptions import SlotUnavailableError


@dataclass(frozen=True)
class Interval:
    """[start, end), both timezone-aware."""

    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: "Interval") -> bool:
        return self.start <= other.start and other.end <= self.end


@dataclass(frozen=True)
class WeeklyHours:
    """One block of opening hours on one weekday (0 = Monday, as in Python)."""

    weekday: int
    start: time
    end: time
    mode: AvailabilityMode = AvailabilityMode.BOTH
    # None: the doctor's default slot length
    slot_minutes: int | None = None
    effective_from: date | None = None
    # inclusive
    effective_to: date | None = None

    def applies_on(self, day: date) -> bool:
        return (
            day.weekday() == self.weekday
            and (self.effective_from is None or day >= self.effective_from)
            and (self.effective_to is None or day <= self.effective_to)
        )


@dataclass(frozen=True)
class BookingPolicy:
    timezone: str
    slot_minutes: int = 20
    # kept free after every appointment
    buffer_minutes: int = 0
    min_notice_minutes: int = 60
    horizon_days: int = 60

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass
class Schedule:
    policy: BookingPolicy
    hours: list[WeeklyHours]
    time_off: list[Interval] = field(default_factory=list)
    # appointments that occupy their time: held and confirmed
    booked: list[Interval] = field(default_factory=list)


@dataclass(frozen=True)
class _Opening:
    interval: Interval
    mode: AvailabilityMode
    slot_minutes: int


def _local(day: date, at: time, zone: ZoneInfo) -> datetime:
    """
    A wall-clock time on a day, as an aware datetime.

    Round-tripping through UTC settles the two awkward cases: a time skipped
    by a spring-forward change lands just after the gap, and a repeated time
    in the autumn takes its first occurrence.
    """
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC).astimezone(zone)


def _openings(schedule: Schedule, day: date) -> Iterator[_Opening]:
    zone = schedule.policy.zone
    for hours in schedule.hours:
        if hours.applies_on(day):
            yield _Opening(
                interval=Interval(_local(day, hours.start, zone), _local(day, hours.end, zone)),
                mode=hours.mode,
                slot_minutes=hours.slot_minutes or schedule.policy.slot_minutes,
            )


def _days(start: datetime, end: datetime, zone: ZoneInfo) -> Iterator[date]:
    day, last = start.astimezone(zone).date(), end.astimezone(zone).date()
    while day <= last:
        yield day
        day += timedelta(days=1)


def _conflict(schedule: Schedule, candidate: Interval) -> Unavailable | None:
    if any(candidate.overlaps(off) for off in schedule.time_off):
        return Unavailable.TIME_OFF

    # the buffer follows every appointment, so pad both sides' ends by it
    buffer = timedelta(minutes=schedule.policy.buffer_minutes)
    padded = Interval(candidate.start, candidate.end + buffer)
    if any(padded.overlaps(Interval(b.start, b.end + buffer)) for b in schedule.booked):
        return Unavailable.TAKEN

    return None


def _bookable_window(schedule: Schedule, now: datetime) -> tuple[datetime, datetime]:
    """The earliest and (exclusive) latest start any booking may have right now."""
    policy = schedule.policy
    return now + timedelta(minutes=policy.min_notice_minutes), now + timedelta(days=policy.horizon_days)


def check_start(schedule: Schedule, start: datetime, now: datetime, mode: AppointmentMode) -> Interval:
    """
    The appointment that starting exactly at `start` would be, or
    SlotUnavailableError saying precisely why not.

    The database re-checks overlap on insert; this is what makes the answer
    explainable ("the doctor is off that day") rather than just "no".
    """
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    if start.second or start.microsecond:
        raise SlotUnavailableError(Unavailable.NOT_WHOLE_MINUTE)

    earliest, latest = _bookable_window(schedule, now)
    if start < earliest:
        raise SlotUnavailableError(Unavailable.TOO_SOON)
    if start >= latest:
        raise SlotUnavailableError(Unavailable.BEYOND_HORIZON)

    wrong_mode = False
    local_day = start.astimezone(schedule.policy.zone).date()
    for opening in _openings(schedule, local_day):
        candidate = Interval(start, start + timedelta(minutes=opening.slot_minutes))
        if not opening.interval.contains(candidate):
            continue
        if not opening.mode.accepts(mode):
            wrong_mode = True
            continue
        if reason := _conflict(schedule, candidate):
            raise SlotUnavailableError(reason)
        return candidate

    raise SlotUnavailableError(Unavailable.WRONG_MODE if wrong_mode else Unavailable.OUTSIDE_HOURS)


def find_slots(
    schedule: Schedule,
    start: datetime,
    end: datetime,
    now: datetime,
    mode: AppointmentMode,
    limit: int | None = None,
) -> list[Interval]:
    """Free grid slots whose start falls in [start, end), earliest first."""
    earliest, latest = _bookable_window(schedule, now)
    buffer = timedelta(minutes=schedule.policy.buffer_minutes)
    slots: list[Interval] = []

    for day in _days(start, end, schedule.policy.zone):
        openings = sorted(_openings(schedule, day), key=lambda o: o.interval.start)
        for opening in openings:
            if not opening.mode.accepts(mode):
                continue
            length = timedelta(minutes=opening.slot_minutes)
            at = opening.interval.start
            while at + length <= opening.interval.end:
                candidate = Interval(at, at + length)
                if start <= at < end and earliest <= at < latest and _conflict(schedule, candidate) is None:
                    slots.append(candidate)
                    if limit is not None and len(slots) >= limit:
                        return slots
                at += length + buffer

    return slots


def suggest_near(
    schedule: Schedule,
    around: datetime,
    now: datetime,
    mode: AppointmentMode,
    count: int = 3,
    search_days: int = 7,
) -> list[Interval]:
    """
    The `count` free slots closest to `around`, in time order: what to offer
    when the time the patient asked for is taken.
    """
    zone = schedule.policy.zone
    day_start = _local(around.astimezone(zone).date(), time(0), zone)
    candidates = find_slots(schedule, day_start - timedelta(days=1), day_start + timedelta(days=search_days), now, mode)
    # equally near: the earlier one, so the patient is not pushed later for nothing
    nearest = sorted(candidates, key=lambda slot: (abs(slot.start - around), slot.start))[:count]

    return sorted(nearest, key=lambda slot: slot.start)
