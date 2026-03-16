from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    session_key: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    session_name: Mapped[str] = mapped_column(String(255))
    session_type: Mapped[str] = mapped_column(String(50))
    circuit_short_name: Mapped[str] = mapped_column(String(100))
    country_name: Mapped[str] = mapped_column(String(100))
    date_start: Mapped[datetime]
    date_end: Mapped[Optional[datetime]]


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        Index("uq_drivers_session_number", "session_key", "driver_number", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[int] = mapped_column(ForeignKey("sessions.session_key"))
    driver_number: Mapped[int]
    broadcast_name: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(200))
    team_name: Mapped[str] = mapped_column(String(100))
    team_colour: Mapped[str] = mapped_column(String(10))
    name_acronym: Mapped[str] = mapped_column(String(5))
    headshot_url: Mapped[Optional[str]] = mapped_column(Text)


class RaceEvent(Base):
    __tablename__ = "race_events"
    __table_args__ = (
        Index("ix_race_events_session_date", "session_key", "event_date"),
        Index("ix_race_events_session_source_date", "session_key", "source", "event_date"),
        Index(
            "uq_race_events_dedup",
            "session_key",
            "source",
            "event_date",
            text("COALESCE(driver_number, 0)"),
            "data_hash",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[int]
    source: Mapped[str] = mapped_column(String(50))
    driver_number: Mapped[Optional[int]]
    lap_number: Mapped[Optional[int]]
    event_date: Mapped[datetime]
    data: Mapped[dict] = mapped_column(JSONB)
    data_hash: Mapped[str] = mapped_column(String(32))


class RadioTranscript(Base):
    __tablename__ = "radio_transcripts"
    __table_args__ = (
        Index("uq_radio_recording_url", "recording_url", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[int]
    driver_number: Mapped[int]
    recording_url: Mapped[str] = mapped_column(Text)
    recording_date: Mapped[datetime]
    transcript: Mapped[Optional[str]] = mapped_column(Text)


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[int]
    window_start: Mapped[datetime]
    window_end: Mapped[datetime]
    prompt_text: Mapped[str] = mapped_column(Text)
    summary_text: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[Optional[str]] = mapped_column(Text)
    embedding = mapped_column(Vector(1536), nullable=True)
