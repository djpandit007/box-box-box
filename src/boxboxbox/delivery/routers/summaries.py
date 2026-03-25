from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from boxboxbox.models import Summary, SummaryType

router = APIRouter()


def _summary_dict(s: Summary) -> dict:
    return {
        "id": s.id,
        "session_key": s.session_key,
        "summary_type": s.summary_type.value,
        "window_start": s.window_start.isoformat(),
        "window_end": s.window_end.isoformat(),
        "summary_text": s.summary_text,
        "audio_url": s.audio_url,
    }


@router.get("/api/sessions/{session_key}/summaries", response_model=None)
async def list_summaries(
    session_key: int,
    request: Request,
    type: str | None = None,
    limit: int = 20,
    before: datetime | None = None,
) -> HTMLResponse | list[dict]:
    stmt = select(Summary).where(Summary.session_key == session_key)
    if type is not None:
        try:
            summary_type = SummaryType(type)
        except ValueError:
            summary_type = None
        if summary_type is not None:
            stmt = stmt.where(Summary.summary_type == summary_type)
    if before is not None:
        stmt = stmt.where(Summary.window_end < before)
    stmt = stmt.order_by(Summary.window_end.desc()).limit(limit)

    async with request.app.state.session_factory() as db:
        result = await db.execute(stmt)
        summaries = result.scalars().all()

    if "text/html" in request.headers.get("accept", ""):
        env = request.app.state.jinja_env
        cards = "".join(env.get_template("partials/summary_card.html").render(summary=s) for s in reversed(summaries))
        return HTMLResponse(cards)

    return [_summary_dict(s) for s in summaries]


@router.get("/api/sessions/{session_key}/summaries/search", response_model=None)
async def search_summaries(
    session_key: int,
    request: Request,
    q: str,
    limit: int = 5,
) -> HTMLResponse | list[dict]:
    embedding_client = request.app.state.embedding_client
    query_vector = await embedding_client.embed(q)

    stmt = (
        select(Summary)
        .where(Summary.session_key == session_key, Summary.embedding.is_not(None))
        .order_by(Summary.embedding.op("<=>")(query_vector))
        .limit(limit)
    )

    async with request.app.state.session_factory() as db:
        result = await db.execute(stmt)
        summaries = result.scalars().all()

    if "text/html" in request.headers.get("accept", ""):
        env = request.app.state.jinja_env
        cards = "".join(env.get_template("partials/summary_card.html").render(summary=s) for s in summaries)
        return HTMLResponse(cards)

    return [_summary_dict(s) for s in summaries]
