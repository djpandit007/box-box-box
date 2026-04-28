from __future__ import annotations

import logging
import pathlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader
from pydantic_ai import Agent
from sqlalchemy import select, text

if TYPE_CHECKING:
    from boxboxbox.summariser.web_search import DigestDeps

from boxboxbox.audio.tts import generate_audio
from boxboxbox.config import settings
from boxboxbox.db import SessionFactory
from boxboxbox.models import Driver, RaceEvent, Session, Summary, SummaryType
from boxboxbox.summariser.agent import _template_key
from boxboxbox.summariser.context import fetch_same_weekend_context, fetch_similar_past_summaries
from boxboxbox.summariser.embeddings import EmbeddingClient
from boxboxbox.summariser.prompt import _format_lap_time

logger = logging.getLogger(__name__)


_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), keep_trailing_newline=True)
_jinja_env.filters["lap_time"] = _format_lap_time


async def generate_digest(
    session_factory: SessionFactory,
    digest_agent: Agent[DigestDeps, str] | Agent[None, str],
    embedding_client: EmbeddingClient,
    session_key: int,
    session_type: str = "Race",
) -> str:
    """Generate a post-race digest from all summaries and store it."""
    async with session_factory() as db:
        # Check if a digest already exists for this session.
        existing_result = await db.execute(
            select(Summary)
            .where(Summary.session_key == session_key, Summary.summary_type == SummaryType.digest)
            .order_by(Summary.window_end.desc())
            .limit(1)
        )
        existing_digest = existing_result.scalar_one_or_none()

        if existing_digest is not None:
            if existing_digest.audio_url:
                logger.info("Digest already exists with audio, reusing.")
                return existing_digest.summary_text

            # Digest text exists but audio is missing — generate audio only.
            logger.info("Digest text exists but audio is missing, generating audio only.")
            if settings.ELEVENLABS_API_KEY:
                audio_url = await generate_audio(existing_digest.summary_text, session_key, session_type)
                if audio_url:
                    existing_digest.audio_url = audio_url
                    await db.commit()
            return existing_digest.summary_text

        result = await db.execute(
            select(Summary)
            .where(Summary.session_key == session_key, Summary.summary_type == SummaryType.window)
            .order_by(Summary.window_start)
        )
        summaries = result.scalars().all()

        if not summaries:
            logger.warning("No summaries found for digest generation")
            return ""

        # Fetch session metadata for the template
        session_result = await db.execute(select(Session).where(Session.session_key == session_key))
        session = session_result.scalar_one_or_none()

        # Fetch final standings from session_result endpoint data (present for race and qualifying)
        standings_result = await db.execute(
            select(RaceEvent)
            .where(RaceEvent.session_key == session_key, RaceEvent.source == "session_result")
            .order_by(text("(data->>'position')::int NULLS LAST"))
        )
        driver_rows = await db.execute(select(Driver).where(Driver.session_key == session_key))
        driver_map = {d.driver_number: d for d in driver_rows.scalars().all()}

        final_standings = []
        for row in standings_result.scalars().all():
            d = row.data
            driver_number = d.get("driver_number")
            driver = driver_map.get(driver_number) if driver_number is not None else None
            name = f"{driver.full_name} ({driver.name_acronym}, {driver.team_name})" if driver else f"#{driver_number}"
            final_standings.append(
                {
                    "position": d.get("position"),
                    "driver": name,
                    "duration": d.get("duration"),
                    "gap_to_leader": d.get("gap_to_leader"),
                    "dnf": d.get("dnf", False),
                    "dns": d.get("dns", False),
                    "dsq": d.get("dsq", False),
                }
            )

        # Derive qualifying eliminations from duration arrays (ordered by position)
        qualifying_eliminations: dict[str, list[dict]] = {}
        for r in final_standings:
            dur = r.get("duration")
            if not isinstance(dur, list) or len(dur) < 3:
                continue
            if dur[0] is not None and dur[1] is None:
                qualifying_eliminations.setdefault("q1", []).append({"driver": r["driver"], "q1_time": dur[0]})
            elif dur[1] is not None and dur[2] is None:
                qualifying_eliminations.setdefault("q2", []).append({"driver": r["driver"], "q2_time": dur[1]})

        # Fetch historical context.
        weekend_context = await fetch_same_weekend_context(db, session_key)

        # Use the last window summary's embedding for past-race similarity search.
        last_summary = summaries[-1] if summaries else None
        historical: list[dict] = []
        if last_summary is not None and last_summary.embedding is not None:
            historical = await fetch_similar_past_summaries(
                db,
                embedding=list(last_summary.embedding),
                exclude_session_key=session_key,
                limit=5,
            )

        digest_prompt = _build_digest_prompt(
            summaries,
            session,
            final_standings,
            qualifying_eliminations or None,
            weekend_context=weekend_context or None,
            historical_summaries=historical or None,
        )

        # Construct deps if web search is enabled.
        run_kwargs: dict = {"user_prompt": digest_prompt}
        if settings.TAVILY_API_KEY and session is not None:
            from boxboxbox.summariser.web_search import DigestDeps

            run_kwargs["deps"] = DigestDeps(
                tavily_api_key=settings.TAVILY_API_KEY,
                circuit_name=session.circuit_short_name,
                session_name=session.session_name,
            )

        logger.info("#" * 60)
        logger.info("POST-RACE DIGEST")
        logger.info("#" * 60)
        async with digest_agent.run_stream(**run_kwargs) as agent_result:
            async for chunk in agent_result.stream_text(delta=True):
                print(chunk, end="", flush=True)
            digest_text = await agent_result.get_output()
        print()  # newline after streamed tokens
        logger.info("#" * 60)

        logger.info("Post-race digest generated")

        embedding = await embedding_client.embed(digest_text)

        digest = Summary(
            session_key=session_key,
            summary_type=SummaryType.digest,
            window_start=summaries[0].window_start,
            window_end=summaries[-1].window_end,
            prompt_text=digest_prompt,
            summary_text=digest_text,
            embedding=embedding,
        )
        db.add(digest)
        await db.commit()

        if settings.ELEVENLABS_API_KEY:
            audio_url = await generate_audio(digest_text, session_key, session_type)
            if audio_url:
                digest.audio_url = audio_url
                await db.commit()

        return digest_text


def _build_digest_prompt(
    summaries: Sequence[Summary],
    session: Session | None,
    final_standings: list[dict] | None = None,
    qualifying_eliminations: dict[str, list[dict]] | None = None,
    weekend_context: dict[str, str] | None = None,
    historical_summaries: list[dict] | None = None,
) -> str:
    """Render the digest prompt template with all race summaries."""
    session_type = session.session_type if session else "Race"
    key = _template_key(session_type)
    template = _jinja_env.get_template(f"{key}_digest.xml.jinja2")
    return template.render(
        session_name=session.session_name if session else "Unknown",
        circuit=session.circuit_short_name if session else "Unknown",
        session_type=session_type,
        final_standings=final_standings or [],
        qualifying_eliminations=qualifying_eliminations,
        weekend_context=weekend_context,
        historical_summaries=historical_summaries,
        summaries=[
            {
                "window_start": s.window_start.strftime("%H:%M:%S"),
                "window_end": s.window_end.strftime("%H:%M:%S"),
                "text": s.summary_text,
            }
            for s in summaries
        ],
    )
