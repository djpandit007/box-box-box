from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from boxboxbox.models import Session, Summary
from boxboxbox.summariser.context import fetch_same_weekend_context, fetch_similar_past_summaries


class TestFetchSimilarPastSummaries:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_embedding(self):
        db = AsyncMock()
        result = await fetch_similar_past_summaries(db, embedding=None, exclude_session_key=1)
        assert result == []
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_matching_summaries(self):
        summary = MagicMock(spec=Summary)
        summary.summary_text = "Hamilton closes to within DRS range."
        session = MagicMock(spec=Session)
        session.circuit_short_name = "Monza"
        session.session_name = "Race"

        row_result = MagicMock()
        row_result.all.return_value = [(summary, session)]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=row_result)

        results = await fetch_similar_past_summaries(db, embedding=[0.1] * 2048, exclude_session_key=99)

        assert len(results) == 1
        assert results[0]["text"] == "Hamilton closes to within DRS range."
        assert results[0]["circuit"] == "Monza"
        assert results[0]["session"] == "Race"
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_matches(self):
        row_result = MagicMock()
        row_result.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=row_result)

        results = await fetch_similar_past_summaries(db, embedding=[0.1] * 2048, exclude_session_key=99)
        assert results == []


class TestFetchSameWeekendContext:
    @pytest.mark.asyncio
    async def test_returns_empty_when_meeting_key_is_none(self):
        current_session = MagicMock(spec=Session)
        current_session.meeting_key = None

        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = current_session

        db = AsyncMock()
        db.execute = AsyncMock(return_value=session_result)

        result = await fetch_same_weekend_context(db, session_key=1)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_digest_from_earlier_session(self):
        current_session = MagicMock(spec=Session)
        current_session.meeting_key = 100
        current_session.session_key = 2
        current_session.date_start = datetime(2026, 3, 16, 14, 0)

        earlier_session = MagicMock(spec=Session)
        earlier_session.session_key = 1
        earlier_session.session_type = "Qualifying"
        earlier_session.date_start = datetime(2026, 3, 15, 14, 0)

        digest_summary = MagicMock(spec=Summary)
        digest_summary.summary_text = "Norris takes pole with a stunning 1:28.456."

        # First call: get current session
        current_result = MagicMock()
        current_result.scalar_one_or_none.return_value = current_session

        # Second call: get weekend sessions
        weekend_result = MagicMock()
        weekend_result.scalars.return_value.all.return_value = [earlier_session]

        # Third call: get digest for earlier session
        digest_result = MagicMock()
        digest_result.scalar_one_or_none.return_value = digest_summary

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[current_result, weekend_result, digest_result])

        result = await fetch_same_weekend_context(db, session_key=2)
        assert "Qualifying" in result
        assert "Norris takes pole" in result["Qualifying"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_earlier_sessions(self):
        current_session = MagicMock(spec=Session)
        current_session.meeting_key = 100
        current_session.session_key = 1
        current_session.date_start = datetime(2026, 3, 15, 10, 0)

        current_result = MagicMock()
        current_result.scalar_one_or_none.return_value = current_session

        weekend_result = MagicMock()
        weekend_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[current_result, weekend_result])

        result = await fetch_same_weekend_context(db, session_key=1)
        assert result == {}
