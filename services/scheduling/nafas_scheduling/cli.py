"""Admin commands for the scheduling service.

    uv run python -m nafas_scheduling.cli set-hours --doctor-id <uuid> --timezone Africa/Cairo \\
        --slot-minutes 20 --hours wed=17:00-21:00 --hours thu=17:00-21:00/in_person
    uv run python -m nafas_scheduling.cli time-off --doctor-id <uuid> --from 2026-10-14T00:00 --to 2026-10-16T00:00

set-hours replaces the doctor's weekly hours as a whole, so the command line
is always the complete truth about them.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete

from nafas_core.db import session_scope
from nafas_scheduling.enums import AvailabilityMode
from nafas_scheduling.models import AvailabilityRule, BookingSettings, TimeOff

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_hours(spec: str) -> tuple[int, time, time, AvailabilityMode]:
    """ "wed=17:00-21:00" or "thu=17:00-21:00/in_person" → (weekday, start, end, mode)."""
    try:
        day, rest = spec.split("=", 1)
        span, _, mode = rest.partition("/")
        start, end = (time.fromisoformat(part) for part in span.split("-", 1))
        weekday = WEEKDAYS[day.strip().lower()[:3]]
        availability = AvailabilityMode(mode) if mode else AvailabilityMode.BOTH
    except (ValueError, KeyError) as exc:
        raise ValueError(f"cannot read hours {spec!r}; expected like wed=17:00-21:00 or thu=17:00-21:00/in_person") from exc

    if end <= start:
        raise ValueError(f"hours {spec!r} end before they start")

    return weekday, start, end, availability


async def set_hours(args: argparse.Namespace) -> None:
    try:
        ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"{args.timezone!r} is not an IANA time zone") from exc
    blocks = [parse_hours(spec) for spec in args.hours]

    async with session_scope(doctor_id=args.doctor_id) as session:
        settings = await session.get(BookingSettings, args.doctor_id) or BookingSettings(doctor_id=args.doctor_id)
        settings.timezone = args.timezone
        settings.slot_minutes = args.slot_minutes
        settings.buffer_minutes = args.buffer_minutes
        session.add(settings)

        await session.execute(delete(AvailabilityRule).where(AvailabilityRule.doctor_id == args.doctor_id))
        for weekday, start, end, mode in blocks:
            session.add(AvailabilityRule(doctor_id=args.doctor_id, weekday=weekday, start_local=start, end_local=end, mode=mode))

    print(f"{len(blocks)} block(s) of weekly hours set for {args.doctor_id} ({args.timezone})")


async def time_off(args: argparse.Namespace) -> None:
    async with session_scope(doctor_id=args.doctor_id) as session:
        zone = ZoneInfo((await session.get(BookingSettings, args.doctor_id)).timezone)
        starts, ends = (datetime.fromisoformat(v).replace(tzinfo=zone) for v in (args.start, args.end))
        session.add(TimeOff(doctor_id=args.doctor_id, starts_at=starts, ends_at=ends, reason=args.reason))

    print(f"time off {starts:%Y-%m-%d %H:%M} to {ends:%Y-%m-%d %H:%M} ({zone.key})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nafas_scheduling.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    hours = commands.add_parser("set-hours", help="replace a doctor's weekly hours and booking settings")
    hours.add_argument("--doctor-id", type=uuid.UUID, required=True)
    hours.add_argument("--timezone", default="Africa/Cairo")
    hours.add_argument("--slot-minutes", type=int, default=20)
    hours.add_argument("--buffer-minutes", type=int, default=0)
    hours.add_argument("--hours", action="append", required=True, help="e.g. wed=17:00-21:00 or thu=17:00-21:00/in_person")

    off = commands.add_parser("time-off", help="block a period, in the doctor's local time")
    off.add_argument("--doctor-id", type=uuid.UUID, required=True)
    off.add_argument("--from", dest="start", required=True)
    off.add_argument("--to", dest="end", required=True)
    off.add_argument("--reason")

    args = parser.parse_args(argv)
    try:
        asyncio.run(set_hours(args) if args.command == "set-hours" else time_off(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
