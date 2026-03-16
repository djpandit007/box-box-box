"""Fetch all endpoint data for the latest session and save as JSON fixtures."""

import argparse
import asyncio
import json
import logging
import pathlib

from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.ingestion.endpoints import ENDPOINTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://api.openf1.org/v1"


async def snapshot(output_dir: pathlib.Path) -> None:
    client = OpenF1Client(BASE_URL)
    try:
        # Resolve the latest session key
        sessions = await client.get("/sessions", {"session_key": "latest"})
        if not sessions:
            logger.error("No session found")
            return

        session_key = sessions[0]["session_key"]
        session_name = sessions[0].get("session_name", "unknown")
        logger.info("Snapshotting session %s (%s)", session_key, session_name)

        dest = output_dir / str(session_key)
        dest.mkdir(parents=True, exist_ok=True)

        # Save session and driver metadata
        for name, path in [("sessions", "/sessions"), ("drivers", "/drivers")]:
            data = await client.get(path, {"session_key": session_key})
            (dest / f"{name}.json").write_text(json.dumps(data, indent=2))
            logger.info("Saved %s: %d records", name, len(data))

        # Save all polling endpoints
        for ep in ENDPOINTS:
            try:
                data = await client.get(ep.path, {"session_key": session_key})
            except Exception:
                logger.warning("Failed to fetch %s, saving empty array", ep.name)
                data = []
            (dest / f"{ep.name}.json").write_text(json.dumps(data, indent=2))
            logger.info("Saved %s: %d records", ep.name, len(data))

    finally:
        await client.close()

    logger.info("Fixtures saved to %s", dest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot latest F1 session data as test fixtures")
    parser.add_argument("--output", default="tests/fixtures", help="Output directory (default: tests/fixtures)")
    args = parser.parse_args()
    asyncio.run(snapshot(pathlib.Path(args.output)))


if __name__ == "__main__":
    main()
