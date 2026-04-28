"""Add sessions.meeting_key column.

Revision ID: 004
Revises: 003
Create Date: 2026-04-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("meeting_key", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "meeting_key")
