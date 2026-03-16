import asyncio
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.endpoints import ENDPOINTS, EndpointConfig, Priority
from boxboxbox.models import Driver, RaceEvent, RadioTranscript, Session

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, client: OpenF1Client, session_factory: async_sessionmaker):
        self._client = client
        self._session_factory = session_factory
        self._session_key: str | int = "latest"
        self._tick = 0
        self._last_dates: dict[str, str] = {}

    async def initialize(self) -> None:
        sessions = await self._client.get("/sessions", {"session_key": self._session_key})
        if not sessions:
            raise RuntimeError("No session found for session_key=latest")

        session_data = sessions[0]
        self._session_key = session_data["session_key"]
        logger.info(
            "Tracking session %s: %s at %s",
            self._session_key,
            session_data.get("session_name", "Unknown"),
            session_data.get("circuit_short_name", "Unknown"),
        )

        async with self._session_factory() as db:
            stmt = pg_insert(Session).values(
                session_key=session_data["session_key"],
                session_name=session_data.get("session_name", ""),
                session_type=session_data.get("session_type", ""),
                circuit_short_name=session_data.get("circuit_short_name", ""),
                country_name=session_data.get("country_name", ""),
                date_start=session_data.get("date_start"),
                date_end=session_data.get("date_end"),
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["session_key"])
            await db.execute(stmt)

            drivers = await self._client.get("/drivers", {"session_key": self._session_key})
            for d in drivers:
                driver_stmt = pg_insert(Driver).values(
                    session_key=self._session_key,
                    driver_number=d["driver_number"],
                    broadcast_name=d.get("broadcast_name", ""),
                    full_name=d.get("full_name", ""),
                    team_name=d.get("team_name", ""),
                    team_colour=d.get("team_colour", ""),
                    name_acronym=d.get("name_acronym", ""),
                    headshot_url=d.get("headshot_url"),
                )
                driver_stmt = driver_stmt.on_conflict_do_nothing(
                    index_elements=["session_key", "driver_number"]
                )
                await db.execute(driver_stmt)

            await db.commit()
        logger.info("Initialized with %d drivers", len(drivers))

    async def poll_once(self) -> None:
        self._tick += 1
        endpoints = [ep for ep in ENDPOINTS if self._should_poll(ep)]
        logger.info("Tick %d: polling %d endpoints", self._tick, len(endpoints))
        await asyncio.gather(*(self._fetch_and_store(ep) for ep in endpoints))

    def _should_poll(self, endpoint: EndpointConfig) -> bool:
        if endpoint.priority == Priority.P1:
            return True
        if endpoint.priority == Priority.P2:
            return self._tick % 3 == 0
        if endpoint.priority == Priority.P3:
            return self._tick % 6 == 0
        return False

    async def _fetch_and_store(self, endpoint: EndpointConfig) -> None:
        params: dict[str, str | int] = {"session_key": self._session_key}

        last_date = self._last_dates.get(endpoint.name)
        if endpoint.date_field and last_date:
            params[f"{endpoint.date_field}>"] = last_date

        try:
            records = await self._client.get(endpoint.path, params)
        except Exception:
            logger.exception("Failed to fetch %s", endpoint.name)
            return

        if not records:
            return

        logger.info("Fetched %d records from %s", len(records), endpoint.name)

        if endpoint.date_field:
            dates = [r.get(endpoint.date_field) for r in records if r.get(endpoint.date_field)]
            if dates:
                self._last_dates[endpoint.name] = max(dates)

        async with self._session_factory() as db:
            if endpoint.name == "team_radio":
                await self._store_radio(db, records)
            else:
                await self._store_events(db, endpoint.name, records)
            await db.commit()

    async def _store_radio(self, db, records: list[dict]) -> None:
        for r in records:
            recording_url = r.get("recording_url")
            if not recording_url:
                continue
            stmt = pg_insert(RadioTranscript).values(
                session_key=self._session_key,
                driver_number=r.get("driver_number", 0),
                recording_url=recording_url,
                recording_date=r.get("date", datetime.min),
                transcript=None,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["recording_url"])
            await db.execute(stmt)

    async def _store_events(self, db, source: str, records: list[dict]) -> None:
        for r in records:
            event_date = r.get("date") or r.get("date_start")
            if not event_date:
                continue
            data_hash = OpenF1Client.hash_event(r)
            stmt = pg_insert(RaceEvent).values(
                session_key=self._session_key,
                source=source,
                driver_number=r.get("driver_number"),
                lap_number=r.get("lap_number"),
                event_date=event_date,
                data=r,
                data_hash=data_hash,
            )
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[
                    "session_key",
                    "source",
                    "event_date",
                    text("COALESCE(driver_number, 0)"),
                    "data_hash",
                ]
            )
            await db.execute(stmt)

    async def run(self, poll_interval: int = 10) -> None:
        await self.initialize()
        logger.info("Poller started (interval=%ds)", poll_interval)
        try:
            while True:
                await self.poll_once()
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Poller stopped")
