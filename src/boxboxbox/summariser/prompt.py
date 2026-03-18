from __future__ import annotations

import pathlib
from collections import defaultdict
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boxboxbox.models import Driver, RaceEvent

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), keep_trailing_newline=True)


async def build_prompt(
    db: AsyncSession,
    session_key: int,
    window_start: datetime,
    window_end: datetime,
    previous_summary: str | None,
) -> str | None:
    """Build an XML-tagged prompt from race events in [window_start, window_end).

    Returns None if there are no events in the window.
    """
    events_by_source = await _fetch_events(db, session_key, window_start, window_end)

    if not events_by_source:
        return None

    driver_map = await _fetch_driver_map(db, session_key)
    context = _build_template_context(events_by_source, driver_map, previous_summary, window_start, window_end)
    template = _jinja_env.get_template("summary_prompt.xml.jinja2")
    return template.render(context)


async def _fetch_events(
    db: AsyncSession,
    session_key: int,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[dict]]:
    """Query RaceEvent rows grouped by source for the given time window."""
    result = await db.execute(
        select(RaceEvent)
        .where(
            RaceEvent.session_key == session_key,
            RaceEvent.event_date >= window_start,
            RaceEvent.event_date < window_end,
        )
        .order_by(RaceEvent.event_date)
    )
    rows = result.scalars().all()
    if not rows:
        return {}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.source].append(row.data)
    return dict(grouped)


async def _fetch_driver_map(db: AsyncSession, session_key: int) -> dict[int, Driver]:
    """Load driver_number -> Driver lookup for name resolution."""
    result = await db.execute(select(Driver).where(Driver.session_key == session_key))
    drivers = result.scalars().all()
    return {d.driver_number: d for d in drivers}


def _driver_name(driver_map: dict[int, Driver], driver_number: int | None) -> str | None:
    """Resolve a driver number to 'Full Name (ACR)' format."""
    if driver_number is None:
        return None
    driver = driver_map.get(driver_number)
    if driver:
        return f"{driver.full_name} ({driver.name_acronym})"
    return f"#{driver_number}"


def _format_time(date_str: str | None) -> str:
    """Extract HH:MM:SS from an ISO datetime string."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return str(date_str)


def _build_template_context(
    events_by_source: dict[str, list[dict]],
    driver_map: dict[int, Driver],
    previous_summary: str | None,
    window_start: datetime,
    window_end: datetime,
) -> dict:
    """Transform raw DB events into clean template context dicts."""
    ctx: dict = {
        "window_start": window_start.strftime("%H:%M:%S"),
        "window_end": window_end.strftime("%H:%M:%S"),
        "previous_summary": previous_summary,
    }

    # Race control
    if "race_control" in events_by_source:
        ctx["race_control"] = [
            {
                "time": _format_time(e.get("date")),
                "lap": e.get("lap_number"),
                "driver": _driver_name(driver_map, e.get("driver_number")),
                "message": e.get("message", ""),
            }
            for e in events_by_source["race_control"]
        ]

    # Overtakes
    if "overtakes" in events_by_source:
        ctx["overtakes"] = [
            {
                "time": _format_time(e.get("date")),
                "position": e.get("position"),
                "overtaking_driver": _driver_name(driver_map, e.get("overtaking_driver_number")) or "Unknown",
                "overtaken_driver": _driver_name(driver_map, e.get("overtaken_driver_number")) or "Unknown",
            }
            for e in events_by_source["overtakes"]
        ]

    # Pit stops
    if "pit" in events_by_source:
        ctx["pit_stops"] = [
            {
                "time": _format_time(e.get("date")),
                "driver": _driver_name(driver_map, e.get("driver_number")) or "Unknown",
                "lap": e.get("lap_number"),
                "stop_duration": e.get("stop_duration", "?"),
                "pit_duration": e.get("pit_duration", "?"),
            }
            for e in events_by_source["pit"]
        ]

    # Positions — collapse to latest snapshot per driver
    if "position" in events_by_source:
        latest_positions: dict[int, dict] = {}
        latest_time = ""
        for e in events_by_source["position"]:
            dn = e.get("driver_number")
            if dn is not None:
                latest_positions[dn] = e
            t = _format_time(e.get("date"))
            if t > latest_time:
                latest_time = t
        standings = sorted(latest_positions.values(), key=lambda x: x.get("position", 99))
        ctx["positions"] = {
            "time": latest_time,
            "standings": [
                {
                    "position": e.get("position"),
                    "driver": _driver_name(driver_map, e.get("driver_number")) or "Unknown",
                }
                for e in standings
            ],
        }

    # Intervals — latest reading per driver
    if "intervals" in events_by_source:
        latest_intervals: dict[int, dict] = {}
        latest_time = ""
        for e in events_by_source["intervals"]:
            dn = e.get("driver_number")
            if dn is not None:
                latest_intervals[dn] = e
            t = _format_time(e.get("date"))
            if t > latest_time:
                latest_time = t
        ctx["intervals"] = {
            "time": latest_time,
            "gaps": [
                {
                    "driver": _driver_name(driver_map, e.get("driver_number")) or "Unknown",
                    "gap_to_leader": e.get("gap_to_leader", "N/A"),
                    "interval": e.get("interval", "N/A"),
                }
                for e in sorted(latest_intervals.values(), key=lambda x: _sort_gap(x.get("gap_to_leader")))
            ],
        }

    # Lap times — only include laps with non-null duration
    if "laps" in events_by_source:
        laps_with_time = [e for e in events_by_source["laps"] if e.get("lap_duration") is not None]
        if laps_with_time:
            ctx["lap_times"] = [
                {
                    "driver": _driver_name(driver_map, e.get("driver_number")) or "Unknown",
                    "lap_number": e.get("lap_number"),
                    "duration": e.get("lap_duration"),
                }
                for e in laps_with_time
            ]

    # Weather — latest reading only
    if "weather" in events_by_source:
        latest = events_by_source["weather"][-1]
        ctx["weather"] = {
            "time": _format_time(latest.get("date")),
            "air_temperature": latest.get("air_temperature"),
            "track_temperature": latest.get("track_temperature"),
            "humidity": latest.get("humidity"),
            "wind_speed": latest.get("wind_speed"),
            "wind_direction": latest.get("wind_direction"),
            "rainfall": latest.get("rainfall", 0),
        }

    # Stints
    if "stints" in events_by_source:
        ctx["stints"] = [
            {
                "driver": _driver_name(driver_map, e.get("driver_number")) or "Unknown",
                "stint_number": e.get("stint_number"),
                "compound": e.get("compound"),
                "lap_start": e.get("lap_start"),
                "lap_end": e.get("lap_end"),
                "tyre_age": e.get("tyre_age_at_start"),
            }
            for e in events_by_source["stints"]
        ]

    return ctx


def _sort_gap(gap) -> float:
    """Sort helper: numeric gaps first, then string gaps (e.g. '+1 LAP')."""
    if isinstance(gap, (int, float)):
        return float(gap)
    return 9999.0
