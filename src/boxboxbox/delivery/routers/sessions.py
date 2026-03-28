from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from boxboxbox.models import Session

router = APIRouter(prefix="/api/sessions")


def _session_dict(s: Session) -> dict:
    return {
        "session_key": s.session_key,
        "session_name": s.session_name,
        "session_type": s.session_type,
        "circuit_short_name": s.circuit_short_name,
        "country_name": s.country_name,
        "date_start": s.date_start.isoformat() if s.date_start else None,
        "date_end": s.date_end.isoformat() if s.date_end else None,
    }


@router.get("")
async def list_sessions(request: Request) -> list[dict]:
    async with request.app.state.session_factory() as db:
        result = await db.execute(select(Session).order_by(Session.date_start.desc()))
        sessions = result.scalars().all()
    return [_session_dict(s) for s in sessions]


@router.get("/{session_key}")
async def get_session(session_key: int, request: Request) -> dict:
    async with request.app.state.session_factory() as db:
        result = await db.execute(select(Session).where(Session.session_key == session_key))
        session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_dict(session)
