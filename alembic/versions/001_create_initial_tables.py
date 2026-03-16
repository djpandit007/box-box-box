"""create initial tables

Revision ID: 001
Revises:
Create Date: 2026-03-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlalchemy.dialects.postgresql
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sessions",
        sa.Column("session_key", sa.Integer(), nullable=False),
        sa.Column("session_name", sa.String(255), nullable=False),
        sa.Column("session_type", sa.String(50), nullable=False),
        sa.Column("circuit_short_name", sa.String(100), nullable=False),
        sa.Column("country_name", sa.String(100), nullable=False),
        sa.Column("date_start", sa.DateTime(), nullable=False),
        sa.Column("date_end", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("session_key"),
    )

    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_key", sa.Integer(), nullable=False),
        sa.Column("driver_number", sa.Integer(), nullable=False),
        sa.Column("broadcast_name", sa.String(100), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("team_name", sa.String(100), nullable=False),
        sa.Column("team_colour", sa.String(10), nullable=False),
        sa.Column("name_acronym", sa.String(5), nullable=False),
        sa.Column("headshot_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["session_key"], ["sessions.session_key"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_drivers_session_number", "drivers", ["session_key", "driver_number"], unique=True)

    op.create_table(
        "race_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_key", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("driver_number", sa.Integer(), nullable=True),
        sa.Column("lap_number", sa.Integer(), nullable=True),
        sa.Column("event_date", sa.DateTime(), nullable=False),
        sa.Column("data", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("data_hash", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_race_events_session_date", "race_events", ["session_key", "event_date"])
    op.create_index("ix_race_events_session_source_date", "race_events", ["session_key", "source", "event_date"])
    op.create_index(
        "uq_race_events_dedup",
        "race_events",
        ["session_key", "source", "event_date", sa.text("COALESCE(driver_number, 0)"), "data_hash"],
        unique=True,
    )

    op.create_table(
        "radio_transcripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_key", sa.Integer(), nullable=False),
        sa.Column("driver_number", sa.Integer(), nullable=False),
        sa.Column("recording_url", sa.Text(), nullable=False),
        sa.Column("recording_date", sa.DateTime(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_radio_recording_url", "radio_transcripts", ["recording_url"], unique=True)

    op.create_table(
        "summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_key", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("audio_url", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("summaries")
    op.drop_table("radio_transcripts")
    op.drop_table("race_events")
    op.drop_table("drivers")
    op.drop_table("sessions")
    op.execute("DROP EXTENSION IF EXISTS vector")
