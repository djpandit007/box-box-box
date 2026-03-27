from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from boxboxbox.ingestion.endpoints import is_non_race_session
from boxboxbox.models import Driver, RaceEvent, Session

router = APIRouter()


@router.get("/api/sessions/{session_key}/standings")
async def get_standings(session_key: int, request: Request) -> list[dict]:
    async with request.app.state.session_factory() as db:
        session_result = await db.execute(select(Session).where(Session.session_key == session_key))
        session = session_result.scalar_one_or_none()
        session_type = session.session_type if session else "Race"

        drivers_result = await db.execute(select(Driver).where(Driver.session_key == session_key))
        drivers = {d.driver_number: d for d in drivers_result.scalars().all()}

        if is_non_race_session(session_type):
            return _build_laps_standings(await _fetch_best_laps(db, session_key), drivers)

        # Race: use position and interval events
        pos_subq = (
            select(RaceEvent.driver_number, func.max(RaceEvent.event_date).label("max_date"))
            .where(RaceEvent.session_key == session_key, RaceEvent.source == "position")
            .group_by(RaceEvent.driver_number)
            .subquery()
        )
        pos_result = await db.execute(
            select(RaceEvent.driver_number, RaceEvent.data)
            .join(
                pos_subq,
                (RaceEvent.driver_number == pos_subq.c.driver_number) & (RaceEvent.event_date == pos_subq.c.max_date),
            )
            .where(RaceEvent.session_key == session_key, RaceEvent.source == "position")
        )
        positions = {row[0]: row[1].get("position") for row in pos_result.all()}

        int_subq = (
            select(RaceEvent.driver_number, func.max(RaceEvent.event_date).label("max_date"))
            .where(RaceEvent.session_key == session_key, RaceEvent.source == "intervals")
            .group_by(RaceEvent.driver_number)
            .subquery()
        )
        int_result = await db.execute(
            select(RaceEvent.driver_number, RaceEvent.data)
            .join(
                int_subq,
                (RaceEvent.driver_number == int_subq.c.driver_number) & (RaceEvent.event_date == int_subq.c.max_date),
            )
            .where(RaceEvent.session_key == session_key, RaceEvent.source == "intervals")
        )
        intervals = {row[0]: row[1].get("interval") for row in int_result.all()}

    standing_rows = []
    for driver_number, position in positions.items():
        driver = drivers.get(driver_number)
        standing_rows.append(
            {
                "driver_number": driver_number,
                "position": position,
                "interval": intervals.get(driver_number),
                "name_acronym": driver.name_acronym if driver else None,
                "full_name": driver.full_name if driver else None,
                "team_name": driver.team_name if driver else None,
                "team_colour": driver.team_colour if driver else None,
            }
        )
    standing_rows.sort(key=lambda r: r["position"] if r["position"] is not None else 999)
    return standing_rows


async def _fetch_best_laps(db, session_key: int) -> dict[int, float]:
    """Return best lap duration per driver for a session."""
    laps_result = await db.execute(
        select(RaceEvent.driver_number, RaceEvent.data).where(
            RaceEvent.session_key == session_key, RaceEvent.source == "laps"
        )
    )
    best: dict[int, float] = {}
    for driver_number, data in laps_result.all():
        dur = data.get("lap_duration")
        if dur is None:
            continue
        if driver_number not in best or dur < best[driver_number]:
            best[driver_number] = dur
    return best


def _build_laps_standings(best_laps: dict[int, float], drivers: dict[int, Driver]) -> list[dict]:
    """Build standings sorted by best lap time, with no-lap drivers at bottom."""
    sorted_drivers = sorted(best_laps, key=lambda d: best_laps[d])
    leader_lap = best_laps[sorted_drivers[0]] if sorted_drivers else None

    rows: list[dict] = []
    for idx, driver_number in enumerate(sorted_drivers, 1):
        driver = drivers.get(driver_number)
        gap = best_laps[driver_number] - leader_lap if leader_lap is not None else None
        rows.append(
            {
                "driver_number": driver_number,
                "position": idx,
                "interval": None,
                "best_lap": best_laps[driver_number],
                "gap": gap,
                "name_acronym": driver.name_acronym if driver else None,
                "full_name": driver.full_name if driver else None,
                "team_name": driver.team_name if driver else None,
                "team_colour": driver.team_colour if driver else None,
            }
        )

    for driver_number, driver in drivers.items():
        if driver_number not in best_laps:
            rows.append(
                {
                    "driver_number": driver_number,
                    "position": len(rows) + 1,
                    "interval": None,
                    "best_lap": None,
                    "gap": None,
                    "name_acronym": driver.name_acronym,
                    "full_name": driver.full_name,
                    "team_name": driver.team_name,
                    "team_colour": driver.team_colour,
                }
            )

    return rows
