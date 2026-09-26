"""The patient's chosen spoken dialect (13 Lahgtna codes) and voice (female, male).

Both nullable: a patient who has not chosen yet is asked, or offered the
dialect-router's suggestion; nothing is assumed for them.

Revision ID: c923aebcc416
Revises: a97be2d76790
Create Date: 2026-09-26 04:00:53.449594

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

DIALECTS = ("eg", "sa", "ma", "bh", "sd", "iq", "lb", "sy", "ly", "ps", "tn", "dz", "ye")
VOICES = ("female", "male")

# revision identifiers, used by Alembic.
revision: str = "c923aebcc416"
down_revision: str | Sequence[str] | None = "a97be2d76790"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postgresql.ENUM(*DIALECTS, name="spoken_dialect", schema="identity").create(op.get_bind())
    postgresql.ENUM(*VOICES, name="voice_gender", schema="identity").create(op.get_bind())
    op.add_column(
        "patients",
        sa.Column(
            "dialect",
            postgresql.ENUM(
                "eg",
                "sa",
                "ma",
                "bh",
                "sd",
                "iq",
                "lb",
                "sy",
                "ly",
                "ps",
                "tn",
                "dz",
                "ye",
                name="spoken_dialect",
                create_type=False,
                schema="identity",
            ),
            nullable=True,
        ),
        schema="identity",
    )
    op.add_column(
        "patients",
        sa.Column(
            "voice", postgresql.ENUM("female", "male", name="voice_gender", create_type=False, schema="identity"), nullable=True
        ),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_column("patients", "voice", schema="identity")
    op.drop_column("patients", "dialect", schema="identity")
    postgresql.ENUM(name="voice_gender", schema="identity").drop(op.get_bind())
    postgresql.ENUM(name="spoken_dialect", schema="identity").drop(op.get_bind())
