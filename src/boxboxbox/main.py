import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from boxboxbox.config import Settings
from boxboxbox.db import get_engine, get_session_factory
from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.poller import Poller
from boxboxbox.models import Summary
from boxboxbox.summariser.agent import create_digest_agent, create_summary_agent
from boxboxbox.summariser.digest import generate_digest
from boxboxbox.summariser.embeddings import EmbeddingClient
from boxboxbox.summariser.loop import SummarisationLoop, generate_historical_summaries

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _get_existing_digest(session_factory, session_key: int) -> str | None:
    """Return the digest text if one already exists for this session."""
    async with session_factory() as db:
        # The digest has the widest time span (covers entire session).
        result = await db.execute(
            select(Summary.summary_text)
            .where(Summary.session_key == session_key)
            .order_by((func.extract("epoch", Summary.window_end) - func.extract("epoch", Summary.window_start)).desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


def _session_is_finished(date_end: datetime) -> bool:
    """Check if session date_end is in the past (both are naive-UTC)."""
    now_utc_naive = datetime.now(UTC).replace(tzinfo=None)
    return date_end < now_utc_naive


async def async_main() -> None:
    settings = Settings()  # ty: ignore[missing-argument]
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    client = OpenF1Client(settings.OPENF1_BASE_URL)
    poller = Poller(client, session_factory)

    # Initialize poller first to resolve the session key
    await poller.initialize()

    # Create summariser components
    summary_agent = create_summary_agent(settings.SUMMARISER_MODEL)
    digest_agent = create_digest_agent(settings.SUMMARISER_MODEL)
    embedding_client = EmbeddingClient(
        api_key=settings.OPENROUTER_API_KEY,
        model=settings.EMBEDDING_MODEL,
    )

    try:
        if _session_is_finished(poller.session_info.date_end):
            # Session already finished — show existing digest or generate from historical data
            logger.info(
                "Session %s (%s) is finished — checking for existing digest",
                poller.session_key,
                poller.session_info.session_name,
            )

            existing_digest = await _get_existing_digest(session_factory, poller.session_key)
            if existing_digest:
                logger.info("#" * 60)
                logger.info(
                    "LAST RACE DIGEST: %s @ %s",
                    poller.session_info.session_name,
                    poller.session_info.circuit_short_name,
                )
                logger.info("#" * 60)
                logger.info(existing_digest)
                logger.info("#" * 60)
            else:
                logger.info("Ingesting historical data for %s...", poller.session_info.session_name)
                await poller.ingest_all()
                logger.info("Data ingestion complete.")

                await generate_historical_summaries(
                    session_factory=session_factory,
                    agent=summary_agent,
                    embedding_client=embedding_client,
                    session_key=poller.session_key,
                    interval_seconds=settings.SUMMARY_INTERVAL_SECONDS,
                )

                logger.info("Generating post-race digest...")
                await generate_digest(session_factory, digest_agent, embedding_client, poller.session_key)
        else:
            # Live session — run real-time polling + summarisation loop
            summariser = SummarisationLoop(
                session_factory=session_factory,
                agent=summary_agent,
                embedding_client=embedding_client,
                session_key=poller.session_key,
                interval_seconds=settings.SUMMARY_INTERVAL_SECONDS,
                grace_seconds=settings.SESSION_END_GRACE_SECONDS,
            )

            poller_task = asyncio.create_task(poller.run(settings.POLL_INTERVAL_SECONDS))

            try:
                await summariser.run()
                await generate_digest(session_factory, digest_agent, embedding_client, poller.session_key)
            finally:
                poller_task.cancel()
                try:
                    await poller_task
                except asyncio.CancelledError:
                    pass
    finally:
        await embedding_client.close()
        await client.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
