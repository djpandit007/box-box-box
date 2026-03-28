import asyncio
import logging
from datetime import UTC, datetime

import uvicorn
from sqlalchemy import func, select

from boxboxbox.config import settings
from boxboxbox.ingestion.endpoints import is_non_race_session
from boxboxbox.db import get_engine, get_session_factory
from boxboxbox.delivery.app import WEB_HOST, WEB_PORT, create_app
from boxboxbox.delivery.ws import SNAPSHOT_INTERVAL_SECONDS, ConnectionManager
from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.poller import Poller
from boxboxbox.models import Driver, RaceEvent, Summary, SummaryType
from boxboxbox.summariser.agent import create_digest_agent, create_summary_agent
from boxboxbox.summariser.digest import generate_digest
from boxboxbox.summariser.embeddings import EmbeddingClient
from boxboxbox.summariser.loop import SummarisationLoop, generate_historical_summaries

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _get_existing_digest(session_factory, session_key: int) -> Summary | None:
    """Return the existing digest Summary if one exists for this session."""
    async with session_factory() as db:
        result = await db.execute(
            select(Summary)
            .where(Summary.session_key == session_key, Summary.summary_type == SummaryType.digest)
            .order_by(Summary.window_end.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


def _session_is_finished(date_end: datetime) -> bool:
    """Check if session date_end is in the past (both are naive-UTC)."""
    now_utc_naive = datetime.now(UTC).replace(tzinfo=None)
    return date_end < now_utc_naive


async def _push_snapshots(session_factory, manager: ConnectionManager, session_key: int, session_type: str) -> None:
    """Periodically push position/interval/weather snapshots to all WebSocket clients."""
    non_race = is_non_race_session(session_type)
    while True:
        try:
            async with session_factory() as db:
                # Best laps — computed first for non-race so positions can be derived from them
                # For qualifying, only consider laps from the current phase
                best_laps: dict[int, dict] = {}
                if non_race:
                    laps_conditions = [
                        RaceEvent.session_key == session_key,
                        RaceEvent.source == "laps",
                    ]
                    # For qualifying, find when the current phase started and reset laps
                    if "Qualifying" in session_type:
                        phase_result = await db.execute(
                            select(RaceEvent.event_date, RaceEvent.data)
                            .where(
                                RaceEvent.session_key == session_key,
                                RaceEvent.source == "race_control",
                            )
                            .order_by(RaceEvent.event_date.desc())
                        )
                        for event_date, data in phase_result.all():
                            qp = data.get("qualifying_phase")
                            msg = (data.get("message") or "").upper()
                            if qp is not None and "FINISHED" in msg:
                                laps_conditions.append(RaceEvent.event_date >= event_date)
                                break

                    laps_result = await db.execute(
                        select(RaceEvent.driver_number, RaceEvent.data).where(*laps_conditions)
                    )
                    for driver_number, data in laps_result.all():
                        dur = data.get("lap_duration")
                        if dur is None:
                            continue
                        existing = best_laps.get(driver_number)
                        if existing is None or dur < existing["lap_duration"]:
                            best_laps[driver_number] = {
                                "lap_duration": dur,
                                "lap_number": data.get("lap_number"),
                            }

                # Positions
                positions: list[dict] = []
                if non_race:
                    # Derive positions from best lap ranking (current phase only)
                    sorted_drivers = sorted(best_laps, key=lambda d: best_laps[d]["lap_duration"])
                    positions = [{"driver_number": dn, "position": idx} for idx, dn in enumerate(sorted_drivers, 1)]
                    # Append eliminated drivers at their final position, then
                    # remaining drivers (no time yet) at the bottom
                    active = set(best_laps)
                    if "Qualifying" in session_type:
                        sr_result = await db.execute(
                            select(RaceEvent.driver_number, RaceEvent.data).where(
                                RaceEvent.session_key == session_key,
                                RaceEvent.source == "session_result",
                            )
                        )
                        for dn, data in sr_result.all():
                            if dn in active or dn is None:
                                continue
                            dur = data.get("duration")
                            if isinstance(dur, list) and len(dur) >= 3:
                                final_pos = data.get("position")
                                if final_pos is not None:
                                    positions.append({"driver_number": dn, "position": final_pos})
                                    active.add(dn)
                    driver_result = await db.execute(
                        select(Driver.driver_number).where(Driver.session_key == session_key)
                    )
                    all_drivers = {row[0] for row in driver_result.all()}
                    no_time = all_drivers - active
                    for dn in no_time:
                        positions.append({"driver_number": dn, "position": len(positions) + 1})
                else:
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
                            (RaceEvent.driver_number == pos_subq.c.driver_number)
                            & (RaceEvent.event_date == pos_subq.c.max_date),
                        )
                        .where(RaceEvent.session_key == session_key, RaceEvent.source == "position")
                    )
                    positions = [
                        {"driver_number": row[0], "position": row[1].get("position")} for row in pos_result.all()
                    ]

                    # Race with no positions yet: fall back to starting grid
                    if not positions:
                        grid_result = await db.execute(
                            select(RaceEvent.driver_number, RaceEvent.data).where(
                                RaceEvent.session_key == session_key, RaceEvent.source == "starting_grid"
                            )
                        )
                        positions = [
                            {"driver_number": row[0], "position": row[1].get("position")} for row in grid_result.all()
                        ]

                # Intervals — only available for race/sprint
                intervals: list[dict] = []
                if not non_race:
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
                            (RaceEvent.driver_number == int_subq.c.driver_number)
                            & (RaceEvent.event_date == int_subq.c.max_date),
                        )
                        .where(RaceEvent.session_key == session_key, RaceEvent.source == "intervals")
                    )
                    intervals = [
                        {"driver_number": row[0], "interval": row[1].get("interval")} for row in int_result.all()
                    ]

                # Latest weather reading
                weather_result = await db.execute(
                    select(RaceEvent.data)
                    .where(RaceEvent.session_key == session_key, RaceEvent.source == "weather")
                    .order_by(RaceEvent.event_date.desc())
                    .limit(1)
                )
                weather_data = weather_result.scalar_one_or_none()
                weather = (
                    {
                        "rainfall": weather_data.get("rainfall", 0),
                        "air_temp": weather_data.get("air_temperature", 0),
                        "track_temp": weather_data.get("track_temperature", 0),
                    }
                    if weather_data
                    else {"rainfall": 0, "air_temp": 0, "track_temp": 0}
                )

            if positions:
                payload: dict = {"positions": positions, "intervals": intervals, "weather": weather}
                if non_race and best_laps:
                    payload["best_laps"] = {str(k): v for k, v in best_laps.items()}
                # For qualifying, include elimination status per driver
                if non_race and "Qualifying" in session_type:
                    sr_result = await db.execute(
                        select(RaceEvent.driver_number, RaceEvent.data).where(
                            RaceEvent.session_key == session_key,
                            RaceEvent.source == "session_result",
                        )
                    )
                    eliminated: dict[str, list[int]] = {}
                    for dn, data in sr_result.all():
                        dur = data.get("duration")
                        if not isinstance(dur, list) or len(dur) < 3 or dn is None:
                            continue
                        if dur[0] is not None and dur[1] is None:
                            eliminated.setdefault("q1", []).append(dn)
                        elif dur[1] is not None and dur[2] is None:
                            eliminated.setdefault("q2", []).append(dn)
                    if eliminated:
                        payload["eliminated"] = eliminated
                await manager.broadcast_json(payload)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error pushing snapshot")

        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)


async def async_main() -> None:
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    client = OpenF1Client(settings.OPENF1_BASE_URL)
    poller = Poller(client, session_factory)

    # Initialize poller first to resolve the session key
    await poller.initialize()

    # Create summariser components
    summary_agent = create_summary_agent(settings.SUMMARISER_MODEL)
    digest_agent = create_digest_agent(settings.DIGEST_MODEL)
    embedding_client = EmbeddingClient(
        api_key=settings.OPENROUTER_API_KEY,
        model=settings.EMBEDDING_MODEL,
    )

    # Always start the delivery server — available for both live and finished sessions.
    is_live = not _session_is_finished(poller.session_info.date_end)
    manager = ConnectionManager()
    app = create_app(
        session_factory,
        embedding_client,
        manager,
        poller.session_key,
        is_live=is_live,
        session_name=poller.session_info.session_name,
        session_type=poller.session_info.session_type,
        country_name=poller.session_info.country_name,
        circuit_short_name=poller.session_info.circuit_short_name,
    )
    web_config = uvicorn.Config(app, host=WEB_HOST, port=WEB_PORT, log_level="warning")
    web_task = asyncio.create_task(uvicorn.Server(web_config).serve())
    snapshot_task = (
        asyncio.create_task(
            _push_snapshots(session_factory, manager, poller.session_key, poller.session_info.session_type)
        )
        if is_live
        else None
    )

    try:
        if not is_live:
            # Session already finished — show existing digest or generate from historical data
            logger.info(
                "Session %s (%s) is finished — checking for existing digest",
                poller.session_key,
                poller.session_info.session_name,
            )

            existing_digest = await _get_existing_digest(session_factory, poller.session_key)
            audio_configured = bool(settings.ELEVENLABS_API_KEY)
            if existing_digest and (existing_digest.audio_url or not audio_configured):
                logger.info("#" * 60)
                logger.info(
                    "LAST RACE DIGEST: %s @ %s",
                    poller.session_info.session_name,
                    poller.session_info.circuit_short_name,
                )
                logger.info("#" * 60)
                logger.info(existing_digest.summary_text)
                logger.info("#" * 60)
            elif existing_digest:
                logger.info(
                    "Digest text exists but audio missing for session %s — generating audio.", poller.session_key
                )
                await generate_digest(
                    session_factory,
                    digest_agent,
                    embedding_client,
                    poller.session_key,
                    session_type=poller.session_info.session_type,
                )
            else:
                logger.info("Ingesting historical data for %s...", poller.session_info.session_name)
                await poller.ingest_all()
                logger.info("Data ingestion complete.")

                await generate_historical_summaries(
                    session_factory=session_factory,
                    agent=summary_agent,
                    embedding_client=embedding_client,
                    session_key=poller.session_key,
                    session_type=poller.session_info.session_type,
                    interval_seconds=settings.SUMMARY_INTERVAL_SECONDS,
                )

                logger.info("Generating post-race digest...")
                await generate_digest(
                    session_factory,
                    digest_agent,
                    embedding_client,
                    poller.session_key,
                    session_type=poller.session_info.session_type,
                )

            logger.info("Web UI at http://localhost:%d — Ctrl-C to stop.", WEB_PORT)
            await web_task
        else:
            # Live session — run real-time polling + summarisation loop
            async def on_summary(summary: Summary) -> None:
                html = app.state.jinja_env.get_template("partials/summary_card.html").render(summary=summary)
                await manager.broadcast_html(html)

            summariser = SummarisationLoop(
                session_factory=session_factory,
                agent=summary_agent,
                embedding_client=embedding_client,
                session_key=poller.session_key,
                session_type=poller.session_info.session_type,
                interval_seconds=settings.SUMMARY_INTERVAL_SECONDS,
                grace_seconds=settings.SESSION_END_GRACE_SECONDS,
                on_summary=on_summary,
            )

            poller_task = asyncio.create_task(poller.run(settings.POLL_INTERVAL_SECONDS))

            try:
                await summariser.run()
                await generate_digest(
                    session_factory,
                    digest_agent,
                    embedding_client,
                    poller.session_key,
                    session_type=poller.session_info.session_type,
                )
                logger.info("Web UI at http://localhost:%d — Ctrl-C to stop.", WEB_PORT)
                await web_task
            finally:
                poller_task.cancel()
                try:
                    await poller_task
                except asyncio.CancelledError:
                    pass
    finally:
        if snapshot_task is not None:
            snapshot_task.cancel()
        web_task.cancel()
        for task in (snapshot_task, web_task):
            if task is None:
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
        await embedding_client.close()
        await client.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
