"""Add summaries.summary_type as a Postgres enum (window vs digest).

Revision ID: 003
Revises: 002
Create Date: 2026-03-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type.
    op.execute("CREATE TYPE summary_type AS ENUM ('window', 'digest')")

    # Add the new column with enum type + default.
    op.add_column(
        "summaries",
        sa.Column(
            "summary_type", sa.Enum("window", "digest", name="summary_type"), nullable=False, server_default="window"
        ),
    )

    # Backfill digests created by `summariser/digest.py` (their prompt uses the <race_summaries ...> template).
    op.execute("UPDATE summaries SET summary_type = 'digest' WHERE prompt_text LIKE '<race_summaries %'")

    # Keep default for future inserts.
    op.execute("ALTER TABLE summaries ALTER COLUMN summary_type SET DEFAULT 'window'")


def downgrade() -> None:
    op.drop_column("summaries", "summary_type")
    op.execute("DROP TYPE summary_type")
