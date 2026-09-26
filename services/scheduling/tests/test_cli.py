from datetime import time

import pytest

from nafas_scheduling.cli import parse_hours
from nafas_scheduling.enums import AvailabilityMode


def test_hours_parse_with_and_without_a_mode():
    assert parse_hours("wed=17:00-21:00") == (2, time(17), time(21), AvailabilityMode.BOTH)
    assert parse_hours("Thursday=09:30-13:00/in_person") == (3, time(9, 30), time(13), AvailabilityMode.IN_PERSON)


@pytest.mark.parametrize("spec", ["wed=21:00-17:00", "xyz=10:00-11:00", "wed 10-11", "wed=10:00-11:00/remote"])
def test_bad_hours_are_refused_with_the_expected_form(spec):
    with pytest.raises(ValueError):
        parse_hours(spec)
