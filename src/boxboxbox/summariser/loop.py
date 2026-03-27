from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pydantic_ai import Agent
from sqlalchemy import func, select

from boxboxbox.db import SessionFactory
from boxboxbox.models import RaceEvent, Session, Summary, SummaryType
from boxboxbox.summariser.embeddings import EmbeddingClient
from boxboxbox.summariser.prompt import build_prompt

logger = logging.getLogger(__name__)


class SummarisationLoop:
    """Orchestrates 60-second summarisation cycles during a live race."""

    def __init__(
        self,
        session_factory: SessionFactory,
        agent: Agent,
        embedding_client: EmbeddingClient,
        session_key: int,
        session_type: str = "Race",
        interval_seconds: int = 60,
        grace_seconds: int = 300,
        on_summary: Callable[[Summary], Awaitable[None]] | None = None,
    ):
        self._session_factory = session_factory
        self._agent = agent
        self._embedding_client = embedding_client
        self._session_key = session_key
        self._session_type = session_type
        self._interval = interval_seconds
        self._grace_seconds = grace_seconds
        self._on_summary = on_summary
        self._last_window_end: datetime | None = None
        self._no_events_since: datetime | None = None

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

        async with self._session_factory() as db:
            previous_summary = await self._get_previous_summary(db)

            prompt = await build_prompt(
                db, self._session_key, window_start, window_end, previous_summary, self._session_type
            )

            if prompt is None:
                if self._no_events_since is None:
                    self._no_events_since = now
                elif (now - self._no_events_since).total_seconds() > self._grace_seconds:
                    return True
                self._last_window_end = window_end
                return False

            self._no_events_since = None

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
                logger.exception("Failed to generate summary for window %s - %s, skipping", window_start, window_end)

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

    async def _get_previous_summary(self, db) -> str | None:
        """Fetch the most recent summary text for narrative continuity."""
        result = await db.execute(
            select(Summary.summary_text)
            .where(Summary.session_key == self._session_key)
            .order_by(Summary.window_end.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def generate_historical_summaries(
    session_factory: SessionFactory,
    agent: Agent,
    embedding_client: EmbeddingClient,
    session_key: int,
    session_type: str = "Race",
    interval_seconds: int = 60,
) -> None:
    """Generate all summaries for a finished session in batch."""
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
        if window_start >= latest:
            logger.info(
                "All windows already summarised up to %s; nothing new to generate.", latest.strftime("%H:%M:%S")
            )
            return
    else:
        window_start = earliest
        previous_summary = None
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
            window_start = window_end
            continue

        logger.info(
            "Generating summary %d/%d [%s - %s]",
            window_num,
            total_windows,
            window_start.strftime("%H:%M:%S"),
            window_end.strftime("%H:%M:%S"),
        )

        async with session_factory() as db:
            prompt = await build_prompt(db, session_key, window_start, window_end, previous_summary, session_type)

            if prompt is not None:
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
                    existing_by_start[window_start] = summary
                except Exception:
                    logger.exception("Failed to generate summary for window %d/%d, skipping", window_num, total_windows)

        window_start = window_end
