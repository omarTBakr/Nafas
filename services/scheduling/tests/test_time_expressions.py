from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from nafas_scheduling.logic.time_expressions import DayPeriod, DayRef, Meridiem, TimeExpression, resolve, resolve_day

CAIRO = ZoneInfo("Africa/Cairo")
# a Monday
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=CAIRO)
TODAY = NOW.date()


def hhmm(values) -> list[str]:
    return [v.strftime("%H:%M") for v in values]


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (DayRef(relative_days=0), date(2026, 10, 5)),
        (DayRef(relative_days=1), date(2026, 10, 6)),  # بكرة
        (DayRef(relative_days=2), date(2026, 10, 7)),  # بعد بكرة
        (DayRef(weekday=2), date(2026, 10, 7)),  # الأربع
        (DayRef(weekday=0), date(2026, 10, 12)),  # "Monday", said on a Monday: next week's
        (DayRef(on=date(2026, 11, 1)), date(2026, 11, 1)),
    ],
)
def test_days(ref, expected):
    assert resolve_day(ref, TODAY) == expected


def test_a_day_ref_names_exactly_one_thing():
    with pytest.raises(ValueError):
        DayRef(relative_days=1, weekday=2)
    with pytest.raises(ValueError):
        DayRef()


def test_tomorrow_after_asr_searches_the_asr_window():
    """ "بكرة بعد العصر": no exact time, so a window to offer slots from."""
    resolution = resolve(TimeExpression(DayRef(relative_days=1), period=DayPeriod.ASR), NOW, "Africa/Cairo")

    assert resolution.day == date(2026, 10, 6)
    assert resolution.candidates == []
    assert hhmm([resolution.search.start, resolution.search.end]) == ["15:00", "18:00"]


def test_an_hour_without_am_or_pm_is_both_until_the_schedule_decides():
    """ "الساعة 5 وتلت" (5:20): 05:20 and 17:20 both stay candidates."""
    resolution = resolve(TimeExpression(DayRef(weekday=2), hour=5, minute=20), NOW, "Africa/Cairo")

    assert hhmm(resolution.candidates) == ["05:20", "17:20"]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (TimeExpression(DayRef(relative_days=1), hour=5, minute=40, meridiem=Meridiem.PM), ["17:40"]),
        (TimeExpression(DayRef(relative_days=1), hour=12, meridiem=Meridiem.AM), ["00:00"]),
        (TimeExpression(DayRef(relative_days=1), hour=17, minute=40), ["17:40"]),
        (TimeExpression(DayRef(relative_days=1), hour=12), ["12:00"]),
        # a period settles am/pm: "الساعة 6 بالليل", "الساعة 9 الصبح", "الساعة 2 الضهر"
        (TimeExpression(DayRef(relative_days=1), hour=6, period=DayPeriod.EVENING), ["18:00"]),
        (TimeExpression(DayRef(relative_days=1), hour=9, period=DayPeriod.MORNING), ["09:00"]),
        (TimeExpression(DayRef(relative_days=1), hour=2, period=DayPeriod.NOON), ["14:00"]),
    ],
)
def test_exact_times(expression, expected):
    assert hhmm(resolve(expression, NOW, "Africa/Cairo").candidates) == expected


def test_a_whole_day_is_searched_when_nothing_narrows_it():
    resolution = resolve(TimeExpression(DayRef(relative_days=2)), NOW, "Africa/Cairo")

    assert hhmm([resolution.search.start]) == ["00:00"]
    assert resolution.search.end.date() == date(2026, 10, 8)


def test_the_night_period_ends_at_midnight():
    resolution = resolve(TimeExpression(DayRef(relative_days=0), period=DayPeriod.NIGHT), NOW, "Africa/Cairo")

    assert resolution.search.end == datetime(2026, 10, 6, 0, 0, tzinfo=CAIRO)


def test_impossible_times_are_refused():
    with pytest.raises(ValueError):
        TimeExpression(DayRef(relative_days=1), hour=17, meridiem=Meridiem.PM)
    with pytest.raises(ValueError):
        TimeExpression(DayRef(relative_days=1), hour=25)
