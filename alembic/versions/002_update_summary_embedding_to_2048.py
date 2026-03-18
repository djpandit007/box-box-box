"""Update Summary embedding dimension to 2048.

Revision ID: 002
Revises: 001
Create Date: 2026-03-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safe reset: embeddings are derived data and can be regenerated.
    op.execute("UPDATE summaries SET embedding = NULL")

    # Ensure extension exists (should already from 001, but harmless).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Alter pgvector dimension.
    op.execute("ALTER TABLE summaries ALTER COLUMN embedding TYPE vector(2048)")


def downgrade() -> None:
    op.execute("UPDATE summaries SET embedding = NULL")
    op.execute("ALTER TABLE summaries ALTER COLUMN embedding TYPE vector(1536)")
