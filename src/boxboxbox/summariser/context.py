from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boxboxbox.models import Session, Summary, SummaryType

logger = logging.getLogger(__name__)


async def fetch_similar_past_summaries(
    db: AsyncSession,
    embedding: list[float] | None,
    exclude_session_key: int,
    limit: int = 3,
    max_distance: float = 0.25,
) -> list[dict]:
    """Find past summaries similar to the given embedding via pgvector cosine distance.

    Returns an empty list if embedding is None or nothing is close enough.
    """
    if embedding is None:
        return []

    distance_expr = Summary.embedding.op("<=>")(embedding)
    stmt = (
        select(Summary, Session)
        .join(Session, Summary.session_key == Session.session_key)
        .where(
            Summary.session_key != exclude_session_key,
            Summary.embedding.is_not(None),
            Summary.summary_type == SummaryType.window,
            distance_expr < max_distance,
        )
        .order_by(distance_expr)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "text": summary.summary_text,
            "circuit": session.circuit_short_name,
            "session": session.session_name,
        }
        for summary, session in rows
    ]


async def fetch_same_weekend_context(
    db: AsyncSession,
    session_key: int,
) -> dict[str, str]:
    """Fetch digest summaries from earlier sessions in the same GP weekend.

    Returns a dict keyed by session type (e.g. {"Qualifying": "..."}).
    Returns empty dict if meeting_key is NULL or no earlier sessions exist.
    """
    current = (await db.execute(select(Session).where(Session.session_key == session_key))).scalar_one_or_none()

    if current is None or current.meeting_key is None:
        return {}

    # Find other sessions in the same meeting that started before this one.
    weekend_sessions = (
        (
            await db.execute(
                select(Session)
                .where(
                    Session.meeting_key == current.meeting_key,
                    Session.session_key != session_key,
                    Session.date_start < current.date_start,
                )
                .order_by(Session.date_start)
            )
        )
        .scalars()
        .all()
    )

    if not weekend_sessions:
        return {}

    context: dict[str, str] = {}
    for sess in weekend_sessions:
        # Prefer the digest summary; fall back to last 3 window summaries.
        digest = (
            await db.execute(
                select(Summary)
                .where(
                    Summary.session_key == sess.session_key,
                    Summary.summary_type == SummaryType.digest,
                )
                .order_by(Summary.window_end.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if digest is not None:
            context[sess.session_type] = digest.summary_text
        else:
            windows = (
                (
                    await db.execute(
                        select(Summary)
                        .where(
                            Summary.session_key == sess.session_key,
                            Summary.summary_type == SummaryType.window,
                        )
                        .order_by(Summary.window_end.desc())
                        .limit(3)
                    )
                )
                .scalars()
                .all()
            )
            if windows:
                context[sess.session_type] = "\n".join(s.summary_text for s in reversed(windows))

    return context
