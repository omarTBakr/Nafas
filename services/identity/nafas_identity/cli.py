"""Admin commands for the identity service.

    uv run python -m nafas_identity.cli seed
    uv run python -m nafas_identity.cli create-doctor --email ... --name-en ... --name-ar ... --specialization cardiology
    uv run python -m nafas_identity.cli disable-account --email ...   (and enable-account)

Doctor accounts are only ever made here: there is no sign-up.
"""

import argparse
import asyncio
import getpass
import sys

from nafas_core.db import session_scope
from nafas_core.exceptions.base import NafasError
from nafas_identity.logic.accounts import create_doctor_account, set_active
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
        )
    print(f"doctor {doctor.id} created for {args.email}")
    print("next: give them booking hours with `python -m nafas_scheduling.cli`")


async def set_account(email: str, active: bool) -> bool:
    async with session_scope() as session:
        found = await set_active(session, email, active)
    print(f"{email}: {'enabled' if active else 'disabled'}" if found else f"no account for {email}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nafas_identity.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("seed", help="create or update the specializations")

    doctor = commands.add_parser("create-doctor", help="create a doctor and their dashboard account")
    doctor.add_argument("--email", required=True)
    doctor.add_argument("--name-en", required=True)
    doctor.add_argument("--name-ar", required=True)
    doctor.add_argument("--specialization", required=True, choices=[s.code for s in SPECIALIZATIONS])
    # for scripts; interactively, leave it out and type it at the prompt
    doctor.add_argument("--password")

    for name, doing in (
        ("disable-account", "turn an account off: no login, sessions end"),
        ("enable-account", "turn it on again"),
    ):
        command = commands.add_parser(name, help=doing)
        command.add_argument("--email", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            asyncio.run(seed())
        elif args.command == "create-doctor":
            asyncio.run(create_doctor(args))
        elif not asyncio.run(set_account(args.email, args.command == "enable-account")):
            return 1
    except NafasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
