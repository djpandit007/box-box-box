from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from boxboxbox.models import Driver, RaceEvent

router = APIRouter()


@router.get("/api/sessions/{session_key}/standings")
async def get_standings(session_key: int, request: Request) -> list[dict]:
    async with request.app.state.session_factory() as db:
        # Latest position per driver
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

        # Latest interval per driver
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

        # Driver info
        drivers_result = await db.execute(select(Driver).where(Driver.session_key == session_key))
        drivers = {d.driver_number: d for d in drivers_result.scalars().all()}

    # Merge and sort by position
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
