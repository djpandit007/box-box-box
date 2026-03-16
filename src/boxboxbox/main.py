import asyncio
import logging

from boxboxbox.config import Settings
from boxboxbox.db import get_engine, get_session_factory
from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.poller import Poller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def async_main() -> None:
    settings = Settings()  # ty: ignore[missing-argument]
    engine = get_engine(settings.DATABASE_URL)
    session_factory = get_session_factory(engine)
    client = OpenF1Client(settings.OPENF1_BASE_URL)
    poller = Poller(client, session_factory)
    try:
        await poller.run(settings.POLL_INTERVAL_SECONDS)
    finally:
        await client.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
