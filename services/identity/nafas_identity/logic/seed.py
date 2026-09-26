from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nafas_identity.models import Specialization
from nafas_identity.specializations import SPECIALIZATIONS


async def seed_specializations(session: AsyncSession) -> tuple[int, int]:
    """
    Makes the specializations table match nafas_identity.specializations.

    Idempotent: a code that exists is updated in place, so re-running after
    editing the data file applies the edit. Returns (created, updated).
    """
    existing = {s.code: s for s in (await session.scalars(select(Specialization))).all()}
    created = updated = 0

    for seed in SPECIALIZATIONS:
        values = {
            "name_en": seed.name_en,
            "name_ar": seed.name_ar,
            "scope_description": seed.scope,
            "in_scope_topics": list(seed.in_scope_topics),
            "always_escalate": list(seed.always_escalate),
        }
        if (row := existing.get(seed.code)) is None:
            session.add(Specialization(code=seed.code, **values))
            created += 1
        else:
            for name, value in values.items():
                setattr(row, name, value)
            updated += 1

    await session.flush()

    return created, updated
