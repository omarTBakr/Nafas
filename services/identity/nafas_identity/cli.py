"""Admin commands for the identity service.

    uv run python -m nafas_identity.cli seed
    uv run python -m nafas_identity.cli create-doctor --email ... --name-en ... --name-ar ... --specialization cardiology

Doctor accounts are only ever made here: there is no sign-up.
"""

import argparse
import asyncio
import getpass
import sys

from nafas_core.db import session_scope
from nafas_core.exceptions.base import NafasError
from nafas_identity.logic.accounts import create_doctor_account
from nafas_identity.logic.seed import seed_specializations
from nafas_identity.specializations import SPECIALIZATIONS


async def seed() -> None:
    async with session_scope() as session:
        created, updated = await seed_specializations(session)
    print(f"specializations: {created} created, {updated} updated")


async def create_doctor(args: argparse.Namespace) -> None:
    password = args.password or getpass.getpass("password (12+ characters): ")
    async with session_scope() as session:
        doctor = await create_doctor_account(
            session,
            email=args.email,
            password=password,
            full_name_en=args.name_en,
            full_name_ar=args.name_ar,
            specialization_code=args.specialization,
            timezone=args.timezone,
            default_slot_minutes=args.slot_minutes,
        )
    print(f"doctor {doctor.id} created for {args.email}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nafas_identity.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("seed", help="create or update the specializations")

    doctor = commands.add_parser("create-doctor", help="create a doctor and their dashboard account")
    doctor.add_argument("--email", required=True)
    doctor.add_argument("--name-en", required=True)
    doctor.add_argument("--name-ar", required=True)
    doctor.add_argument("--specialization", required=True, choices=[s.code for s in SPECIALIZATIONS])
    doctor.add_argument("--timezone", default="Africa/Cairo")
    doctor.add_argument("--slot-minutes", type=int, default=20)
    # for scripts; interactively, leave it out and type it at the prompt
    doctor.add_argument("--password")

    args = parser.parse_args(argv)
    try:
        asyncio.run(seed() if args.command == "seed" else create_doctor(args))
    except NafasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
