from __future__ import annotations

import logging
import pathlib
from collections.abc import Sequence

from jinja2 import Environment, FileSystemLoader
from pydantic_ai import Agent
from sqlalchemy import select

from boxboxbox.audio.tts import generate_audio
from boxboxbox.config import settings
from boxboxbox.db import SessionFactory
from boxboxbox.models import Session, Summary, SummaryType
from boxboxbox.summariser.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), keep_trailing_newline=True)


async def generate_digest(
    session_factory: SessionFactory,
    digest_agent: Agent,
    embedding_client: EmbeddingClient,
    session_key: int,
) -> str:
    """Generate a post-race digest from all summaries and store it."""
    async with session_factory() as db:
        result = await db.execute(
            select(Summary)
            .where(Summary.session_key == session_key, Summary.summary_type == SummaryType.window)
            .order_by(Summary.window_start)
        )
        summaries = result.scalars().all()

        if not summaries:
            logger.warning("No summaries found for digest generation")
            return ""

        existing_result = await db.execute(
            select(Summary).where(Summary.session_key == session_key, Summary.summary_type == SummaryType.digest)
        )
        existing_digest = existing_result.scalar_one_or_none()

        if existing_digest and existing_digest.summary_text and existing_digest.audio_url:
            logger.info("The text and audio digest for the race already exists")
            return existing_digest.summary_text

        if not existing_digest or not existing_digest.summary_text:
            # Fetch session metadata for the template
            session_result = await db.execute(select(Session).where(Session.session_key == session_key))
            session = session_result.scalar_one_or_none()

            digest_prompt = _build_digest_prompt(summaries, session)

            logger.info("#" * 60)
            logger.info("POST-RACE DIGEST")
            logger.info("#" * 60)
            async with digest_agent.run_stream(user_prompt=digest_prompt) as agent_result:
                async for text in agent_result.stream_text(delta=True):
                    print(text, end="", flush=True)
                digest_text: str = await agent_result.get_output()
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

        if existing_digest and not existing_digest.audio_url:
            if settings.ELEVENLABS_API_KEY or settings.SARVAM_API_KEY:
                audio_url = await generate_audio(digest_text, session_key)
                if audio_url:
                    digest.audio_url = audio_url
                    await db.commit()

        return digest_text


def _build_digest_prompt(summaries: Sequence[Summary], session: Session | None) -> str:
    """Render the digest prompt template with all race summaries."""
    template = _jinja_env.get_template("digest_prompt.xml.jinja2")
    return template.render(
        session_name=session.session_name if session else "Unknown",
        circuit=session.circuit_short_name if session else "Unknown",
        summaries=[
            {
                "window_start": s.window_start.strftime("%H:%M:%S"),
                "window_end": s.window_end.strftime("%H:%M:%S"),
                "text": s.summary_text,
            }
            for s in summaries
        ],
    )
