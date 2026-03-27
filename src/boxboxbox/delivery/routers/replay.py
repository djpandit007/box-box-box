from __future__ import annotations

import pathlib

from fastapi import APIRouter, Request
from sqlalchemy import select

from boxboxbox.ingestion.endpoints import is_non_race_session
from boxboxbox.models import Driver, RaceEvent, Session, Summary, SummaryType

router = APIRouter()


def _audio_url(path: str | None) -> str | None:
    """Convert a file-system audio path to a URL path."""
    if not path:
        return None
    return "/audio/" + pathlib.PurePosixPath(path).name


@router.get("/api/sessions/{session_key}/replay")
async def get_replay_data(session_key: int, request: Request) -> dict:
    async with request.app.state.session_factory() as db:
        # Session metadata
        session_result = await db.execute(select(Session).where(Session.session_key == session_key))
        session = session_result.scalar_one_or_none()
        session_start = session.date_start.isoformat() if session else None
        session_end = session.date_end.isoformat() if session and session.date_end else None

        # Event sources depend on session type
        non_race = is_non_race_session(session.session_type) if session else False
        sources = ["weather", "laps"] if non_race else ["position", "intervals", "weather", "laps"]

        events_result = await db.execute(
            select(RaceEvent.source, RaceEvent.driver_number, RaceEvent.event_date, RaceEvent.data)
            .where(
                RaceEvent.session_key == session_key,
                RaceEvent.source.in_(sources),
            )
            .order_by(RaceEvent.event_date)
        )
        rows = events_result.all()

        position_events = []
        interval_events = []
        weather_events = []
        lap_events = []

        for source, driver_number, event_date, data in rows:
            ts = event_date.isoformat()
            if source == "position":
                position_events.append(
                    {
                        "driver_number": driver_number,
                        "event_date": ts,
                        "position": data.get("position"),
                    }
                )
            elif source == "intervals":
                interval_events.append(
                    {
                        "driver_number": driver_number,
                        "event_date": ts,
                        "interval": data.get("interval"),
                    }
                )
            elif source == "weather":
                weather_events.append(
                    {
                        "event_date": ts,
                        "rainfall": data.get("rainfall", 0),
                        "air_temp": data.get("air_temperature", 0),
                        "track_temp": data.get("track_temperature", 0),
                    }
                )
            elif source == "laps":
                lap_events.append(
                    {
                        "driver_number": driver_number,
                        "event_date": ts,
                        "lap_duration": data.get("lap_duration"),
                        "lap_number": data.get("lap_number"),
                    }
                )

        # Driver metadata
        drivers_result = await db.execute(select(Driver).where(Driver.session_key == session_key))
        drivers = {
            d.driver_number: {
                "name_acronym": d.name_acronym,
                "full_name": d.full_name,
                "team_name": d.team_name,
                "team_colour": d.team_colour,
                "headshot_url": d.headshot_url,
            }
            for d in drivers_result.scalars().all()
        }

        # All window summaries
        summaries_result = await db.execute(
            select(Summary)
            .where(
                Summary.session_key == session_key,
                Summary.summary_type == SummaryType.window,
            )
            .order_by(Summary.window_end)
        )
        summaries = [
            {
                "window_start": s.window_start.isoformat(),
                "window_end": s.window_end.isoformat(),
                "summary_text": s.summary_text,
                "audio_url": _audio_url(s.audio_url),
            }
            for s in summaries_result.scalars().all()
        ]

        # Post-session digest
        digest_result = await db.execute(
            select(Summary)
            .where(Summary.session_key == session_key, Summary.summary_type == SummaryType.digest)
            .order_by(Summary.window_end.desc())
            .limit(1)
        )
        digest_row = digest_result.scalar_one_or_none()
        digest = (
            {"summary_text": digest_row.summary_text, "audio_url": _audio_url(digest_row.audio_url)}
            if digest_row
            else None
        )

    return {
        "session_name": session.session_name if session else None,
        "session_type": session.session_type if session else None,
        "circuit_short_name": session.circuit_short_name if session else None,
        "session_start": session_start,
        "session_end": session_end,
        "events": {
            "position": position_events,
            "intervals": interval_events,
            "weather": weather_events,
            "laps": lap_events,
        },
        "drivers": drivers,
        "summaries": summaries,
        "digest": digest,
    }
