import asyncio
import logging

from boxboxbox.config import Settings
from boxboxbox.db import get_engine, get_session_factory
from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.poller import Poller
from boxboxbox.summariser.agent import create_digest_agent, create_summary_agent
from boxboxbox.summariser.digest import generate_digest
from boxboxbox.summariser.embeddings import EmbeddingClient
from boxboxbox.summariser.loop import SummarisationLoop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


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
        # Summariser runs until session ends, then returns
        await summariser.run()
        # Generate post-race digest
        await generate_digest(session_factory, digest_agent, embedding_client, poller.session_key)
    finally:
        # Cancel the poller and clean up
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass
        await embedding_client.close()
        await client.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
