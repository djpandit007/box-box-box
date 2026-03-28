from __future__ import annotations

import pathlib
from collections import defaultdict
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boxboxbox.ingestion.endpoints import is_non_race_session
from boxboxbox.models import Driver, RaceEvent

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), keep_trailing_newline=True)


def _format_lap_time(seconds: float | None) -> str:
    """Format seconds as M:SS.mmm (e.g. 88.456 -> 1:28.456)."""
    if seconds is None:
        return "N/A"
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:06.3f}"


_jinja_env.filters["lap_time"] = _format_lap_time


async def build_prompt(
    db: AsyncSession,
    session_key: int,
    window_start: datetime,
    window_end: datetime,
    previous_summary: str | None,
    session_type: str = "Race",
) -> str | None:
    """Build an XML-tagged prompt from race events in [window_start, window_end).

    Returns None if there are no events in the window.
    """
    events_by_source = await _fetch_events(db, session_key, window_start, window_end)

    if not events_by_source:
        return None

    driver_map = await _fetch_driver_map(db, session_key)

    non_race = is_non_race_session(session_type)
    best_laps: dict[int, float] = {}
    session_results: dict[int, dict] = {}
    qualifying_phase: int | None = None
    if non_race:
        phase_start: datetime | None = None
        if "Qualifying" in session_type:
            session_results = await _fetch_session_results(db, session_key)
            qualifying_phase = await _fetch_qualifying_phase(db, session_key, window_end)
            phase_start = await _fetch_phase_start_time(db, session_key, window_end)
        best_laps = await _fetch_best_laps(db, session_key, window_end, from_time=phase_start)

    context = _build_template_context(
        events_by_source,
        driver_map,
        previous_summary,
        window_start,
        window_end,
        session_type,
        best_laps=best_laps,
        session_results=session_results,
        qualifying_phase=qualifying_phase,
    )
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


async def _fetch_best_laps(
    db: AsyncSession, session_key: int, up_to: datetime, from_time: datetime | None = None
) -> dict[int, float]:
    """Return best lap duration per driver for laps in [from_time, up_to)."""
    conditions = [
        RaceEvent.session_key == session_key,
        RaceEvent.source == "laps",
        RaceEvent.event_date < up_to,
    ]
    if from_time is not None:
        conditions.append(RaceEvent.event_date >= from_time)
    result = await db.execute(select(RaceEvent.driver_number, RaceEvent.data).where(*conditions))
    best: dict[int, float] = {}
    for driver_number, data in result.all():
        dur = data.get("lap_duration")
        if dur is None or driver_number is None:
            continue
        if driver_number not in best or dur < best[driver_number]:
            best[driver_number] = dur
    return best


async def _fetch_phase_start_time(db: AsyncSession, session_key: int, up_to: datetime) -> datetime | None:
    """Return the timestamp of the most recent 'SESSION FINISHED' race_control event.

    If found, the current qualifying phase started after this event.
    Returns None if no phase has ended yet (i.e. still in Q1).
    """
    result = await db.execute(
        select(RaceEvent.event_date, RaceEvent.data)
        .where(
            RaceEvent.session_key == session_key,
            RaceEvent.source == "race_control",
            RaceEvent.event_date < up_to,
        )
        .order_by(RaceEvent.event_date.desc())
    )
    for event_date, data in result.all():
        qp = data.get("qualifying_phase")
        msg = (data.get("message") or "").upper()
        if qp is not None and "FINISHED" in msg:
            return event_date
    return None


async def _fetch_qualifying_phase(db: AsyncSession, session_key: int, up_to: datetime) -> int | None:
    """Return the latest qualifying_phase from race_control events up to the given time."""
    result = await db.execute(
        select(RaceEvent.data)
        .where(
            RaceEvent.session_key == session_key,
            RaceEvent.source == "race_control",
            RaceEvent.event_date < up_to,
        )
        .order_by(RaceEvent.event_date.desc())
    )
    for (data,) in result.all():
        qp = data.get("qualifying_phase")
        if qp is not None:
            return qp
    return None


async def _fetch_session_results(db: AsyncSession, session_key: int) -> dict[int, dict]:
    """Return session_result data keyed by driver_number."""
    result = await db.execute(
        select(RaceEvent.driver_number, RaceEvent.data).where(
            RaceEvent.session_key == session_key,
            RaceEvent.source == "session_result",
        )
    )
    return {dn: data for dn, data in result.all() if dn is not None}


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
    session_type: str = "Race",
    best_laps: dict[int, float] | None = None,
    session_results: dict[int, dict] | None = None,
    qualifying_phase: int | None = None,
) -> dict:
    """Transform raw DB events into clean template context dicts."""
    phase_labels = {1: "Q1", 2: "Q2", 3: "Q3"}
    ctx: dict = {
        "window_start": window_start.strftime("%H:%M:%S"),
        "window_end": window_end.strftime("%H:%M:%S"),
        "previous_summary": previous_summary,
        "session_type": session_type,
    }
    if qualifying_phase is not None:
        ctx["qualifying_phase"] = phase_labels.get(qualifying_phase, f"Q{qualifying_phase}")

    # Check if this window has any meaningful lap data
    has_laps = "laps" in events_by_source and any(e.get("lap_duration") is not None for e in events_by_source["laps"])
    has_race_control = "race_control" in events_by_source
    if not has_laps and not has_race_control:
        ctx["no_significant_data"] = True

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

    # Non-race standings — sorted by best lap so far
    if best_laps:
        sorted_drivers = sorted(best_laps, key=lambda d: best_laps[d])
        leader_lap = best_laps[sorted_drivers[0]] if sorted_drivers else None
        standings_list = []
        for idx, dn in enumerate(sorted_drivers, 1):
            standings_list.append(
                {
                    "position": idx,
                    "driver": _driver_name(driver_map, dn) or f"#{dn}",
                    "best_lap": best_laps[dn],
                    "gap": best_laps[dn] - leader_lap if leader_lap else None,
                }
            )
        # For qualifying, append eliminated drivers below active ones
        # Q2 eliminated first (finished higher), then Q1 eliminated
        if session_results:
            active_drivers = set(best_laps)
            by_position = sorted(session_results.items(), key=lambda kv: kv[1].get("position") or 999)
            q2_elim = []
            q1_elim = []
            for dn, data in by_position:
                if dn in active_drivers:
                    continue
                duration = data.get("duration")
                if not isinstance(duration, list) or len(duration) < 3:
                    continue
                if duration[1] is not None and duration[2] is None:
                    q2_elim.append((dn, duration[1], "Q2"))
                elif duration[0] is not None and duration[1] is None:
                    q1_elim.append((dn, duration[0], "Q1"))
            for group in (q2_elim, q1_elim):
                for dn, elim_time, phase_label in group:
                    standings_list.append(
                        {
                            "position": len(standings_list) + 1,
                            "driver": _driver_name(driver_map, dn) or f"#{dn}",
                            "best_lap": elim_time,
                            "gap": None,
                            "eliminated": phase_label,
                        }
                    )
        ctx["standings"] = standings_list

    # Qualifying phase results — triggered by race_control "SESSION FINISHED" events
    # qualifying_phase=1 ended -> show Q1 eliminated drivers
    # qualifying_phase=2 ended -> show Q2 eliminated drivers (not Q1 again)
    # qualifying_phase=3 ended -> show top 10 from final standings
    if session_results and "race_control" in events_by_source:
        ended_phase: int | None = None
        for e in events_by_source["race_control"]:
            qp = e.get("qualifying_phase")
            if qp is not None and "FINISHED" in (e.get("message") or "").upper():
                ended_phase = qp

        if ended_phase is not None:
            by_position = sorted(session_results.items(), key=lambda kv: kv[1].get("position") or 999)

            if ended_phase == 1:
                eliminated = []
                for dn, data in by_position:
                    duration = data.get("duration")
                    if isinstance(duration, list) and len(duration) >= 2:
                        name = _driver_name(driver_map, dn) or f"#{dn}"
                        if duration[0] is not None and duration[1] is None:
                            eliminated.append({"driver": name, "q1_time": duration[0]})
                if eliminated:
                    ctx["qualifying_eliminations"] = {"q1": eliminated}

            elif ended_phase == 2:
                eliminated = []
                for dn, data in by_position:
                    duration = data.get("duration")
                    if isinstance(duration, list) and len(duration) >= 3:
                        name = _driver_name(driver_map, dn) or f"#{dn}"
                        if duration[1] is not None and duration[2] is None:
                            eliminated.append({"driver": name, "q2_time": duration[1]})
                if eliminated:
                    ctx["qualifying_eliminations"] = {"q2": eliminated}

            elif ended_phase == 3:
                top10 = []
                for dn, data in by_position[:10]:
                    name = _driver_name(driver_map, dn) or f"#{dn}"
                    duration = data.get("duration")
                    q3_time = duration[2] if isinstance(duration, list) and len(duration) >= 3 else None
                    top10.append(
                        {
                            "position": data.get("position"),
                            "driver": name,
                            "q3_time": q3_time,
                        }
                    )
                if top10:
                    ctx["qualifying_top10"] = top10

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
