from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from boxboxbox.delivery.app import create_app
from boxboxbox.delivery.ws import ConnectionManager
from boxboxbox.models import Session, Summary, SummaryType


def _make_session_obj(key: int = 1234) -> Session:
    s = Session()
    s.session_key = key
    s.session_name = "Race"
    s.session_type = "Race"
    s.circuit_short_name = "Monza"
    s.country_name = "Italy"
    s.date_start = datetime(2026, 9, 7, 13, 0)
    s.date_end = datetime(2026, 9, 7, 15, 0)
    return s


def _make_summary_obj(session_key: int = 1234, text: str = "Hamilton leads.") -> Summary:
    s = Summary()
    s.id = 1
    s.session_key = session_key
    s.summary_type = SummaryType.window
    s.window_start = datetime(2026, 9, 7, 13, 0)
    s.window_end = datetime(2026, 9, 7, 13, 1)
    s.prompt_text = "prompt"
    s.summary_text = text
    s.audio_url = None
    s.embedding = None
    return s


def _make_app(db_execute_side_effects: list):
    """Create a test app with mocked session_factory."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=db_execute_side_effects)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=db)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=session_cm)
    embedding_client = AsyncMock()
    embedding_client.embed = AsyncMock(return_value=[0.1] * 2048)

    manager = ConnectionManager()
    app = create_app(session_factory, embedding_client, manager, session_key=1234)
    return app, embedding_client


@pytest.fixture
def transport_for(request):
    """Helper to create httpx.AsyncClient for a given app."""

    async def _make(app):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return _make


class TestSessionsRouter:
    @pytest.mark.asyncio
    async def test_list_sessions(self):
        session_obj = _make_session_obj()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [session_obj]

        app, _ = _make_app([result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["session_key"] == 1234
        assert data[0]["circuit_short_name"] == "Monza"

    @pytest.mark.asyncio
    async def test_get_session(self):
        session_obj = _make_session_obj()
        result = MagicMock()
        result.scalar_one_or_none.return_value = session_obj

        app, _ = _make_app([result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions/1234")

        assert resp.status_code == 200
        assert resp.json()["session_key"] == 1234

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None

        app, _ = _make_app([result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions/9999")

        assert resp.status_code == 404


class TestSummariesRouter:
    @pytest.mark.asyncio
    async def test_list_summaries_json(self):
        summary_obj = _make_summary_obj()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [summary_obj]

        app, _ = _make_app([result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions/1234/summaries")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["summary_text"] == "Hamilton leads."

    @pytest.mark.asyncio
    async def test_list_summaries_html(self):
        summary_obj = _make_summary_obj()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [summary_obj]

        app, _ = _make_app([result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions/1234/summaries", headers={"Accept": "text/html"})

        assert resp.status_code == 200
        assert "Hamilton leads." in resp.text
        assert "summary-timeline" in resp.text

    @pytest.mark.asyncio
    async def test_search_embeds_query_and_returns_results(self):
        summary_obj = _make_summary_obj(text="Safety car deployed.")
        result = MagicMock()
        result.scalars.return_value.all.return_value = [summary_obj]

        app, embedding_client = _make_app([result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions/1234/summaries/search?q=safety+car")

        assert resp.status_code == 200
        embedding_client.embed.assert_awaited_once_with("safety car")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["summary_text"] == "Safety car deployed."


class TestStandingsRouter:
    @pytest.mark.asyncio
    async def test_standings_returns_merged_data(self):
        # Mock three DB calls: positions, intervals, drivers
        pos_result = MagicMock()
        pos_result.all.return_value = [(1, {"position": 1}), (33, {"position": 2})]

        int_result = MagicMock()
        int_result.all.return_value = [(33, {"interval": 0.8})]

        driver1 = MagicMock()
        driver1.driver_number = 1
        driver1.name_acronym = "VER"
        driver1.full_name = "Max Verstappen"
        driver1.team_name = "Red Bull"
        driver1.team_colour = "3671C6"

        driver33 = MagicMock()
        driver33.driver_number = 33
        driver33.name_acronym = "HAM"
        driver33.full_name = "Lewis Hamilton"
        driver33.team_name = "Mercedes"
        driver33.team_colour = "27F4D2"

        drivers_result = MagicMock()
        drivers_result.scalars.return_value.all.return_value = [driver1, driver33]

        app, _ = _make_app([pos_result, int_result, drivers_result])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/sessions/1234/standings")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Sorted by position
        assert data[0]["position"] == 1
        assert data[0]["name_acronym"] == "VER"
        assert data[1]["position"] == 2
        assert data[1]["interval"] == 0.8
        assert data[1]["name_acronym"] == "HAM"
