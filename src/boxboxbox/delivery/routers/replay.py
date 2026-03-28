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

        # All event sources — intervals and starting_grid only exist for race/sprint
        non_race = is_non_race_session(session.session_type) if session else False
        sources = ["weather", "laps"]
        if not non_race:
            sources += ["position", "intervals", "starting_grid"]

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
        starting_grid_events = []

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
            elif source == "starting_grid":
                starting_grid_events.append(
                    {
                        "driver_number": driver_number,
                        "position": data.get("position"),
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

        # For qualifying, compute phase boundary timestamps and elimination status
        phase_boundaries: list[str] = []
        eliminated: dict[str, list[int]] = {}
        session_result_positions: dict[int, int] = {}
        session_result_times: dict[int, float] = {}
        if non_race and session and "Qualifying" in session.session_type:
            rc_result = await db.execute(
                select(RaceEvent.event_date, RaceEvent.data)
                .where(
                    RaceEvent.session_key == session_key,
                    RaceEvent.source == "race_control",
                )
                .order_by(RaceEvent.event_date)
            )
            for event_date, data in rc_result.all():
                qp = data.get("qualifying_phase")
                msg = (data.get("message") or "").upper()
                if qp is not None and "FINISHED" in msg:
                    phase_boundaries.append(event_date.isoformat())

            sr_result = await db.execute(
                select(RaceEvent.driver_number, RaceEvent.data).where(
                    RaceEvent.session_key == session_key,
                    RaceEvent.source == "session_result",
                )
            )
            for dn, data in sr_result.all():
                if dn is None:
                    continue
                final_pos = data.get("position")
                if final_pos is not None:
                    session_result_positions[dn] = final_pos
                dur = data.get("duration")
                if not isinstance(dur, list) or len(dur) < 3:
                    continue
                if dur[0] is not None and dur[1] is None:
                    eliminated.setdefault("q1", []).append(dn)
                    session_result_times[dn] = dur[0]
                elif dur[1] is not None and dur[2] is None:
                    eliminated.setdefault("q2", []).append(dn)
                    session_result_times[dn] = dur[1]

    return {
        "session_name": session.session_name if session else None,
        "session_type": session.session_type if session else None,
        "circuit_short_name": session.circuit_short_name if session else None,
        "session_start": session_start,
        "session_end": session_end,
        "phase_boundaries": phase_boundaries,
        "eliminated": eliminated,
        "session_result_times": session_result_times,
        "events": {
            "position": position_events,
            "intervals": interval_events,
            "weather": weather_events,
            "laps": lap_events,
            "starting_grid": starting_grid_events,
            "session_result_positions": session_result_positions,
        },
        "drivers": drivers,
        "summaries": summaries,
        "digest": digest,
    }
