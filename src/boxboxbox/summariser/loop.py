from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pydantic_ai import Agent
from sqlalchemy import func, select

from boxboxbox.db import SessionFactory
from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.endpoints import is_non_race_session
from boxboxbox.models import RaceEvent, Session, Summary, SummaryType
from boxboxbox.summariser.context import fetch_same_weekend_context, fetch_similar_past_summaries
from boxboxbox.summariser.embeddings import EmbeddingClient
from boxboxbox.observability import tracer
from boxboxbox.summariser.prompt import build_prompt, check_session_status

logger = logging.getLogger(__name__)


async def _fetch_total_laps(client: OpenF1Client, session_key: int) -> int | None:
    """Fetch total race laps from the P1 session result."""
    try:
        results = await client.get("/session_result", params={"session_key": session_key, "position": 1})
        if results:
            return results[0].get("number_of_laps")
    except Exception:
        logger.debug("Could not fetch total laps for session %d", session_key)
    return None


class SummarisationLoop:
    """Orchestrates 60-second summarisation cycles during a live race."""

    def __init__(
        self,
        session_factory: SessionFactory,
        agent: Agent,
        embedding_client: EmbeddingClient,
        client: OpenF1Client,
        session_key: int,
        session_type: str = "Race",
        interval_seconds: int = 60,
        grace_seconds: int = 300,
        on_summary: Callable[[Summary], Awaitable[None]] | None = None,
    ):
        self._session_factory = session_factory
        self._agent = agent
        self._embedding_client = embedding_client
        self._client = client
        self._session_key = session_key
        self._session_type = session_type
        self._interval = interval_seconds
        self._grace_seconds = grace_seconds
        self._on_summary = on_summary
        self._last_window_end: datetime | None = None
        self._no_events_since: datetime | None = None
        self._session_status_checked = False
        self._session_started_at: datetime | None = None
        self._session_finished_at: datetime | None = None
        self._total_laps: int | None = None
        self._weekend_context: dict[str, str] | None = None

    async def run(self) -> None:
        """Run the summarisation loop until the session ends."""
        logger.info("Summarisation loop started (interval=%ds)", self._interval)
        try:
            while True:
                session_ended = await self.summarise_once()
                if session_ended:
                    logger.info("Session appears to have ended")
                    break
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("Summarisation loop cancelled")

    async def summarise_once(self) -> bool:
        """Generate one summary for the current window.

        Returns True if the session appears to have ended (no events for grace period).
        """
        now = datetime.now(UTC)
        window_end = now

        if self._last_window_end is None:
            window_start = await self._earliest_event_date()
            if window_start is None:
                # No events at all yet — wait for the poller to populate data
                return False
        else:
            window_start = self._last_window_end

        # Check session status via API (re-check until both start and finish are known).
        if not self._session_status_checked or (self._session_finished_at is None):
            status = await check_session_status(self._client, self._session_key)
            self._session_started_at = status.started_at
            self._session_finished_at = status.finished_at
            self._session_status_checked = True
        session_started = self._session_started_at is not None
        session_finished = self._session_finished_at is not None and window_start >= self._session_finished_at

        # Fetch total laps for race-type sessions (cached after first success).
        if self._total_laps is None and not is_non_race_session(self._session_type):
            self._total_laps = await _fetch_total_laps(self._client, self._session_key)

        async with self._session_factory() as db:
            with tracer.start_as_current_span("summarise_window") as span:
                span.set_attribute("session_key", self._session_key)
                span.set_attribute("session_type", self._session_type)
                span.set_attribute("window_start", window_start.isoformat())
                span.set_attribute("window_end", window_end.isoformat())

                previous = await self._get_previous_summary(db)
                previous_summary = previous.summary_text if previous else None

                # Fetch same-weekend context once and cache.
                if self._weekend_context is None:
                    self._weekend_context = await fetch_same_weekend_context(db, self._session_key)

                # Fetch similar past summaries using previous summary's embedding.
                historical: list[dict] = []
                if previous is not None and previous.embedding is not None:
                    historical = await fetch_similar_past_summaries(
                        db,
                        embedding=list(previous.embedding),
                        exclude_session_key=self._session_key,
                    )

                prompt = await build_prompt(
                    db,
                    self._session_key,
                    window_start,
                    window_end,
                    previous_summary,
                    self._session_type,
                    session_started=session_started,
                    session_finished=session_finished,
                    total_laps=self._total_laps,
                    weekend_context=self._weekend_context or None,
                    historical_summaries=historical or None,
                )

                if prompt is None:
                    span.set_attribute("input.value", "[no-events]")
                    if not session_started:
                        # Pre-session with no interesting data — store canned text.
                        summary = Summary(
                            session_key=self._session_key,
                            summary_type=SummaryType.window,
                            window_start=window_start,
                            window_end=window_end,
                            prompt_text="[pre-session]",
                            summary_text="The session has not yet started.",
                        )
                        db.add(summary)
                        await db.commit()
                        span.set_attribute("output.value", summary.summary_text)
                        if self._on_summary is not None:
                            try:
                                await self._on_summary(summary)
                            except Exception:
                                logger.exception("on_summary callback failed; continuing")
                    elif session_finished:
                        # Post-session with no interesting data — store canned text.
                        summary = Summary(
                            session_key=self._session_key,
                            summary_type=SummaryType.window,
                            window_start=window_start,
                            window_end=window_end,
                            prompt_text="[post-session]",
                            summary_text="The session has ended.",
                        )
                        db.add(summary)
                        await db.commit()
                        span.set_attribute("output.value", summary.summary_text)
                        if self._on_summary is not None:
                            try:
                                await self._on_summary(summary)
                            except Exception:
                                logger.exception("on_summary callback failed; continuing")
                    else:
                        if self._no_events_since is None:
                            self._no_events_since = now
                        elif (now - self._no_events_since).total_seconds() > self._grace_seconds:
                            return True
                    self._last_window_end = window_end
                    return False

                self._no_events_since = None
                span.set_attribute("input.value", prompt[:500])

                try:
                    logger.info("=" * 60)
                    logger.info("[%s - %s]", window_start.strftime("%H:%M:%S"), window_end.strftime("%H:%M:%S"))
                    async with self._agent.run_stream(user_prompt=prompt) as result:
                        async for text in result.stream_text(delta=True):
                            print(text, end="", flush=True)
                        summary_text = await result.get_output()
                    print()  # newline after streamed tokens
                    logger.info("=" * 60)

                    logger.info("Summary: %s", summary_text[:120])
                    span.set_attribute("output.value", summary_text[:1000])

                    embedding = await self._embedding_client.embed(summary_text)

                    summary = Summary(
                        session_key=self._session_key,
                        summary_type=SummaryType.window,
                        window_start=window_start,
                        window_end=window_end,
                        prompt_text=prompt,
                        summary_text=summary_text,
                        embedding=embedding,
                    )
                    db.add(summary)
                    await db.commit()

                    if self._on_summary is not None:
                        try:
                            await self._on_summary(summary)
                        except Exception:
                            logger.exception("on_summary callback failed; continuing")
                except Exception:
                    logger.exception(
                        "Failed to generate summary for window %s - %s, skipping", window_start, window_end
                    )

        self._last_window_end = window_end
        return False

    async def _earliest_event_date(self) -> datetime | None:
        """Find the race start time (prefer Session.date_start, fallback to earliest event)."""
        async with self._session_factory() as db:
            # Prefer the official race start time from the sessions table.
            session_result = await db.execute(
                select(Session.date_start).where(Session.session_key == self._session_key)
            )
            race_start = session_result.scalar_one_or_none()
            if race_start is not None:
                return race_start

            # Fallback: earliest event date if for some reason we don't have the session row.
            events_result = await db.execute(
                select(func.min(RaceEvent.event_date)).where(RaceEvent.session_key == self._session_key)
            )
            return events_result.scalar_one_or_none()

    async def _get_previous_summary(self, db) -> Summary | None:
        """Fetch the most recent summary for narrative continuity and embedding reuse."""
        result = await db.execute(
            select(Summary)
            .where(
                Summary.session_key == self._session_key,
                Summary.summary_type == SummaryType.window,
            )
            .order_by(Summary.window_end.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def generate_historical_summaries(
    session_factory: SessionFactory,
    agent: Agent,
    embedding_client: EmbeddingClient,
    client: OpenF1Client,
    session_key: int,
    session_type: str = "Race",
    interval_seconds: int = 60,
) -> None:
    """Generate all summaries for a finished session in batch."""
    status = await check_session_status(client, session_key)
    session_started_at = status.started_at
    session_finished_at = status.finished_at
    total_laps = await _fetch_total_laps(client, session_key) if not is_non_race_session(session_type) else None

    async with session_factory() as db:
        result = await db.execute(
            select(func.min(RaceEvent.event_date), func.max(RaceEvent.event_date)).where(
                RaceEvent.session_key == session_key
            )
        )
        row = result.one()
        earliest, latest = row[0], row[1]

        # Prefer the official race start time, if available.
        session_result = await db.execute(select(Session.date_start).where(Session.session_key == session_key))
        race_start = session_result.scalar_one_or_none()
        if race_start is not None and earliest is not None:
            # Start historical windows at the later of the first event and the race start,
            # so we don't summarise pre-race telemetry as race action.
            if race_start > earliest:
                earliest = race_start

        weekend_context = await fetch_same_weekend_context(db, session_key)

        # Load any existing window summaries so we can display them and resume generation.
        existing_result = await db.execute(
            select(Summary)
            .where(Summary.session_key == session_key, Summary.summary_type == SummaryType.window)
            .order_by(Summary.window_start)
        )
        existing_summaries = existing_result.scalars().all()

    if earliest is None or latest is None:
        logger.warning("No events found for session %d — nothing to summarise", session_key)
        return

    existing_by_start: dict[datetime, Summary] = {s.window_start: s for s in existing_summaries}
    if existing_summaries:
        logger.info("Found %d existing window summaries; reusing them.", len(existing_summaries))
        for s in existing_summaries:
            logger.info("=" * 60)
            logger.info("[%s - %s] (existing)", s.window_start.strftime("%H:%M:%S"), s.window_end.strftime("%H:%M:%S"))
            print(s.summary_text, end="\n\n", flush=True)
        logger.info("=" * 60)

    total_seconds = (latest - earliest).total_seconds()
    total_windows = max(1, int(total_seconds / interval_seconds) + 1)
    logger.info(
        "Generating summaries for %d windows (%s - %s)",
        total_windows,
        earliest.strftime("%H:%M:%S"),
        latest.strftime("%H:%M:%S"),
    )

    if existing_summaries:
        last = existing_summaries[-1]
        window_start = last.window_end
        previous_summary: str | None = last.summary_text
        previous_obj: Summary | None = last
        if window_start >= latest:
            logger.info(
                "All windows already summarised up to %s; nothing new to generate.", latest.strftime("%H:%M:%S")
            )
            return
    else:
        window_start = earliest
        previous_summary = None
        previous_obj = None
    window_num = len(existing_summaries)

    while window_start < latest:
        window_num += 1
        window_end = window_start + timedelta(seconds=interval_seconds)
        if window_end > latest:
            window_end = latest + timedelta(seconds=1)

        existing = existing_by_start.get(window_start)
        if existing is not None:
            logger.info(
                "Skipping summary %d/%d [%s - %s] (already exists)",
                window_num,
                total_windows,
                window_start.strftime("%H:%M:%S"),
                window_end.strftime("%H:%M:%S"),
            )
            print(existing.summary_text, end="\n\n", flush=True)
            previous_summary = existing.summary_text
            previous_obj = existing
            window_start = window_end
            continue

        logger.info(
            "Generating summary %d/%d [%s - %s]",
            window_num,
            total_windows,
            window_start.strftime("%H:%M:%S"),
            window_end.strftime("%H:%M:%S"),
        )

        session_started = session_started_at is not None and window_start >= session_started_at
        session_finished = session_finished_at is not None and window_start >= session_finished_at

        async with session_factory() as db:
            historical: list[dict] = []
            if previous_obj is not None and previous_obj.embedding is not None:
                historical = await fetch_similar_past_summaries(
                    db,
                    embedding=list(previous_obj.embedding),
                    exclude_session_key=session_key,
                )

            prompt = await build_prompt(
                db,
                session_key,
                window_start,
                window_end,
                previous_summary,
                session_type,
                session_started=session_started,
                session_finished=session_finished,
                total_laps=total_laps,
                weekend_context=weekend_context or None,
                historical_summaries=historical or None,
            )

            if prompt is None and not session_started:
                # Pre-session with no interesting data — store canned text.
                canned = "The session has not yet started."
                summary = Summary(
                    session_key=session_key,
                    summary_type=SummaryType.window,
                    window_start=window_start,
                    window_end=window_end,
                    prompt_text="[pre-session]",
                    summary_text=canned,
                )
                db.add(summary)
                await db.commit()
                previous_summary = canned
                previous_obj = None
                existing_by_start[window_start] = summary
                logger.info("[%s - %s] %s", window_start.strftime("%H:%M:%S"), window_end.strftime("%H:%M:%S"), canned)
            elif prompt is None and session_finished:
                # Post-session with no interesting data — store canned text.
                canned = "The session has ended."
                summary = Summary(
                    session_key=session_key,
                    summary_type=SummaryType.window,
                    window_start=window_start,
                    window_end=window_end,
                    prompt_text="[post-session]",
                    summary_text=canned,
                )
                db.add(summary)
                await db.commit()
                previous_summary = canned
                previous_obj = None
                existing_by_start[window_start] = summary
                logger.info("[%s - %s] %s", window_start.strftime("%H:%M:%S"), window_end.strftime("%H:%M:%S"), canned)
            elif prompt is not None:
                try:
                    logger.info("=" * 60)
                    logger.info("[%s - %s]", window_start.strftime("%H:%M:%S"), window_end.strftime("%H:%M:%S"))
                    async with agent.run_stream(user_prompt=prompt) as result:
                        async for text in result.stream_text(delta=True):
                            print(text, end="", flush=True)
                        summary_text = await result.get_output()
                    print()  # newline after streamed tokens
                    logger.info("=" * 60)

                    embedding = await embedding_client.embed(summary_text)

                    summary = Summary(
                        session_key=session_key,
                        summary_type=SummaryType.window,
                        window_start=window_start,
                        window_end=window_end,
                        prompt_text=prompt,
                        summary_text=summary_text,
                        embedding=embedding,
                    )
                    db.add(summary)
                    await db.commit()

                    previous_summary = summary_text
                    previous_obj = summary
                    existing_by_start[window_start] = summary
                except Exception:
                    logger.exception("Failed to generate summary for window %d/%d, skipping", window_num, total_windows)

        window_start = window_end
