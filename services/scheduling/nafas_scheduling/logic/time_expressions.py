"""
Turning what a patient said about time into concrete times, deterministically.

The language model does not do date arithmetic: it only fills a
TimeExpression from the patient's words ("بكرة بعد العصر" → tomorrow, period
asr; "next Tuesday 5:40" → weekday 1, 5:40, no am/pm). `resolve` then does
the arithmetic in the doctor's time zone, where it can be tested.

An hour without am/pm and without a period that settles it (the "5" in
"الساعة 5") yields both candidates; the caller keeps whichever falls in the
doctor's hours and asks the patient when both do. Nothing here guesses.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from nafas_scheduling.logic.slots import Interval


class DayPeriod(StrEnum):
    """Parts of the day as patients name them, including by prayer time."""

    MORNING = "morning"  # الصبح
    NOON = "noon"  # الضهر
    AFTERNOON = "afternoon"  # بعد الضهر
    ASR = "asr"  # العصر
    MAGHRIB = "maghrib"  # المغرب
    EVENING = "evening"  # بالليل (early)
    NIGHT = "night"  # بالليل (late)


# Local hours each period spans, [start, end). Prayer times move through the
# year; these are generous windows to search, not prayer timetables, and the
# patient confirms the exact time offered.
PERIOD_HOURS: dict[DayPeriod, tuple[int, int]] = {
    DayPeriod.MORNING: (8, 12),
    DayPeriod.NOON: (12, 15),
    DayPeriod.AFTERNOON: (12, 17),
    DayPeriod.ASR: (15, 18),
    DayPeriod.MAGHRIB: (17, 20),
    DayPeriod.EVENING: (17, 22),
    DayPeriod.NIGHT: (20, 24),
}

_PM_PERIODS = {DayPeriod.AFTERNOON, DayPeriod.ASR, DayPeriod.MAGHRIB, DayPeriod.EVENING, DayPeriod.NIGHT}


class Meridiem(StrEnum):
    AM = "am"
    PM = "pm"


@dataclass(frozen=True)
class DayRef:
    """Exactly one of: days from today, a weekday (0 = Monday), or a date."""

    relative_days: int | None = None
    weekday: int | None = None
    on: date | None = None

    def __post_init__(self):
        if sum(x is not None for x in (self.relative_days, self.weekday, self.on)) != 1:
            raise ValueError("a DayRef names exactly one of relative_days, weekday, on")
        if self.weekday is not None and not 0 <= self.weekday <= 6:
            raise ValueError("weekday is 0 (Monday) to 6 (Sunday)")
        if self.relative_days is not None and self.relative_days < 0:
            raise ValueError("relative_days cannot be negative")


@dataclass(frozen=True)
class TimeExpression:
    day: DayRef
    # 0-23, or 1-12 with or without a meridiem
    hour: int | None = None
    minute: int = 0
    meridiem: Meridiem | None = None
    period: DayPeriod | None = None

    def __post_init__(self):
        if self.hour is not None and not 0 <= self.hour <= 23:
            raise ValueError("hour is 0 to 23")
        if not 0 <= self.minute <= 59:
            raise ValueError("minute is 0 to 59")
        if self.meridiem is not None and (self.hour is None or not 1 <= self.hour <= 12):
            raise ValueError("am/pm needs an hour from 1 to 12")


@dataclass(frozen=True)
class Resolution:
    day: date
    # exact starts the patient may have meant: none, one, or an am/pm pair
    candidates: list[datetime]
    # where to look for slots: the named period, or the whole day
    search: Interval


def resolve_day(ref: DayRef, today: date) -> date:
    """
    The calendar day meant. A bare weekday is its next occurrence after today:
    "Wednesday", said on a Wednesday, means next week's.
    """
    if ref.on is not None:
        return ref.on
    if ref.relative_days is not None:
        return today + timedelta(days=ref.relative_days)

    ahead = (ref.weekday - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def _hours(expr: TimeExpression) -> list[int]:
    """The 24-hour clock hours the expression may mean."""
    hour = expr.hour
    if expr.meridiem is Meridiem.AM:
        return [0 if hour == 12 else hour]
    if expr.meridiem is Meridiem.PM:
        return [12 if hour == 12 else hour + 12]
    if hour == 0 or hour > 12:
        return [hour]
    if hour == 12:
        # "12" alone is noon; midnight appointments are asked for explicitly
        return [12]
    if expr.period in _PM_PERIODS or (expr.period is DayPeriod.NOON and hour <= 3):
        return [hour + 12]
    if expr.period is DayPeriod.MORNING:
        return [hour]

    return [hour, hour + 12]


def resolve(expr: TimeExpression, now: datetime, timezone: str) -> Resolution:
    zone = ZoneInfo(timezone)
    day = resolve_day(expr.day, now.astimezone(zone).date())

    def at(hour: int, minute: int = 0) -> datetime:
        # hour 24 is the following midnight, the end of the NIGHT period
        base = datetime.combine(day, time(0), tzinfo=zone) + timedelta(hours=hour, minutes=minute)
        return base.astimezone(zone)

    if expr.period is not None:
        first, last = PERIOD_HOURS[expr.period]
        search = Interval(at(first), at(last))
    else:
        search = Interval(at(0), at(24))

    candidates = [at(h, expr.minute) for h in _hours(expr)] if expr.hour is not None else []

    return Resolution(day=day, candidates=candidates, search=search)
