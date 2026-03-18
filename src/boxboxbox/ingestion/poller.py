import asyncio
import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.endpoints import ENDPOINTS, EndpointConfig, Priority
from boxboxbox.ingestion.schemas import ENDPOINT_MODELS, DriverResponse, SessionResponse
from boxboxbox.models import Driver, RaceEvent, RadioTranscript, Session

__all__ = ["Poller"]

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, client: OpenF1Client, session_factory: async_sessionmaker):
        self._client = client
        self._session_factory = session_factory
        self._session_key: str | int = "latest"
        self._session_response: SessionResponse | None = None
        self._tick = 0
        self._last_dates: dict[str, str] = {}
        self._initialized = False

    @property
    def session_key(self) -> int:
        """Return the resolved session key. Only valid after initialize()."""
        if not self._initialized:
            raise RuntimeError("Poller not initialized — call initialize() first")
        return self._session_key  # type: ignore[return-value]

    @property
    def session_info(self) -> SessionResponse:
        """Return the session metadata. Only valid after initialize()."""
        if not self._initialized or self._session_response is None:
            raise RuntimeError("Poller not initialized — call initialize() first")
        return self._session_response

    async def initialize(self) -> None:
        # Restrict to the race session so we get the actual race start time.
        sessions: list[SessionResponse] = await self._client.get(
            "/sessions",
            {"session_key": self._session_key, "session_type": "Race"},
            model=SessionResponse,
        )
        if not sessions:
            raise RuntimeError("No session found for session_key=latest")

        s: SessionResponse = sessions[0]
        self._session_key = s.session_key
        self._session_response = s
        logger.info(
            "Tracking session %s: %s at %s",
            self._session_key,
            s.session_name,
            s.circuit_short_name,
        )

        async with self._session_factory() as db:
            stmt = pg_insert(Session).values(
                session_key=s.session_key,
                session_name=s.session_name,
                session_type=s.session_type,
                circuit_short_name=s.circuit_short_name,
                country_name=s.country_name,
                date_start=s.date_start,
                date_end=s.date_end,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["session_key"])
            await db.execute(stmt)

            drivers = await self._client.get("/drivers", {"session_key": self._session_key}, model=DriverResponse)
            for d in drivers:
                driver_stmt = pg_insert(Driver).values(
                    session_key=self._session_key,
                    driver_number=d.driver_number,
                    broadcast_name=d.broadcast_name,
                    full_name=d.full_name,
                    team_name=d.team_name,
                    team_colour=d.team_colour,
                    name_acronym=d.name_acronym,
                    headshot_url=d.headshot_url,
                )
                driver_stmt = driver_stmt.on_conflict_do_nothing(index_elements=["session_key", "driver_number"])
                await db.execute(driver_stmt)

            await db.commit()
        self._initialized = True
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
            raw_records = await self._client.get(endpoint.path, params)
        except Exception:
            logger.exception("Failed to fetch %s", endpoint.name)
            return

        if not raw_records:
            return

        # Validate via Pydantic schema, then dump back to dict for storage
        model_cls = ENDPOINT_MODELS.get(endpoint.name)
        if model_cls:
            validated = [model_cls.model_validate(r) for r in raw_records]
            records = [v.model_dump(mode="json") for v in validated]
        else:
            records = raw_records

        logger.info("Fetched %d records from %s", len(records), endpoint.name)

        if endpoint.date_field:
            dates = [r.get(endpoint.date_field) for r in records if r.get(endpoint.date_field)]
            if dates:
                # Records may contain datetimes (after Pydantic validation) or raw strings.
                latest = max(dates)
                if isinstance(latest, datetime):
                    self._last_dates[endpoint.name] = latest.isoformat()
                else:
                    self._last_dates[endpoint.name] = str(latest)

        async with self._session_factory() as db:
            if endpoint.name == "team_radio":
                await self._store_radio(db, records)
            else:
                await self._store_events(db, endpoint.name, records)
            await db.commit()

    @staticmethod
    def _parse_dt(value) -> datetime | None:
        """Coerce a value to datetime (handles both str and datetime inputs)."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    async def _store_radio(self, db, records: list[dict]) -> None:
        for r in records:
            recording_url = r.get("recording_url")
            if not recording_url:
                continue
            stmt = pg_insert(RadioTranscript).values(
                session_key=self._session_key,
                driver_number=r.get("driver_number", 0),
                recording_url=recording_url,
                recording_date=self._parse_dt(r.get("date")) or datetime.min,
                transcript=None,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["recording_url"])
            await db.execute(stmt)

    async def _store_events(self, db, source: str, records: list[dict]) -> None:
        for r in records:
            event_date = self._parse_dt(r.get("date") or r.get("date_start"))
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

    async def ingest_all(self) -> None:
        """One-shot fetch of all endpoints for the session (ignores priority tiers)."""
        logger.info("Ingesting all data for session %s", self._session_key)
        await asyncio.gather(*(self._fetch_and_store(ep) for ep in ENDPOINTS))

    async def run(self, poll_interval: int = 10) -> None:
        if not self._initialized:
            await self.initialize()
        logger.info("Poller started (interval=%ds)", poll_interval)
        try:
            while True:
                await self.poll_once()
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            logger.info("Poller stopped")
