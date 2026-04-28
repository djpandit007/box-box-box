from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boxboxbox.ingestion.client import OpenF1Client
from boxboxbox.summariser.loop import SummarisationLoop
from boxboxbox.summariser.prompt import SessionStatus


def _make_stream_result(text: str):
    stream_result = AsyncMock()

    async def _stream_text(delta=False):
        yield text

    stream_result.stream_text = _stream_text
    stream_result.get_output = AsyncMock(return_value=text)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=stream_result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_session_factory(earliest: datetime):
    """Factory that returns two context managers: one for _earliest_event_date, one for summarise_once body."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.add = MagicMock()
    session.commit = AsyncMock()

    # _get_previous_summary returns None
    prev_result = MagicMock()
    prev_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=prev_result)

    earliest_result = MagicMock()
    earliest_result.scalar_one_or_none.return_value = earliest

    call_count = 0

    def make_session():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock(execute=AsyncMock(return_value=earliest_result)))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    return make_session, session


class TestOnSummaryCallback:
    @pytest.mark.asyncio
    @patch(
        "boxboxbox.summariser.loop.check_session_status",
        new_callable=AsyncMock,
        return_value=SessionStatus(datetime(2026, 3, 15, 6, 0, tzinfo=UTC), None),
    )
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_callback_fired_after_commit(self, mock_build_prompt, _mock_check):
        mock_build_prompt.return_value = "<race_window>test</race_window>"
        agent = AsyncMock()
        agent.run_stream = MagicMock(return_value=_make_stream_result("Some summary text."))
        embedding_client = AsyncMock()
        embedding_client.embed = AsyncMock(return_value=[0.0] * 1536)

        callback = AsyncMock()
        factory, session = _make_session_factory(datetime(2026, 3, 15, 6, 0, tzinfo=UTC))

        loop = SummarisationLoop(
            session_factory=factory,
            agent=agent,
            embedding_client=embedding_client,
            client=MagicMock(spec=OpenF1Client),
            session_key=12345,
            on_summary=callback,
        )

        ended = await loop.summarise_once()

        assert ended is False
        session.commit.assert_awaited_once()
        callback.assert_awaited_once()
        # Callback receives the Summary object
        summary_arg = callback.call_args[0][0]
        assert summary_arg.summary_text == "Some summary text."

    @pytest.mark.asyncio
    @patch(
        "boxboxbox.summariser.loop.check_session_status",
        new_callable=AsyncMock,
        return_value=SessionStatus(datetime(2026, 3, 15, 6, 0, tzinfo=UTC), None),
    )
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_callback_exception_does_not_break_loop(self, mock_build_prompt, _mock_check):
        mock_build_prompt.return_value = "<race_window>test</race_window>"
        agent = AsyncMock()
        agent.run_stream = MagicMock(return_value=_make_stream_result("Text."))
        embedding_client = AsyncMock()
        embedding_client.embed = AsyncMock(return_value=[0.0] * 1536)

        failing_callback = AsyncMock(side_effect=RuntimeError("callback exploded"))
        factory, session = _make_session_factory(datetime(2026, 3, 15, 6, 0, tzinfo=UTC))

        loop = SummarisationLoop(
            session_factory=factory,
            agent=agent,
            embedding_client=embedding_client,
            client=MagicMock(spec=OpenF1Client),
            session_key=12345,
            on_summary=failing_callback,
        )

        # Should not raise despite callback failure
        ended = await loop.summarise_once()
        assert ended is False
        failing_callback.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(
        "boxboxbox.summariser.loop.check_session_status",
        new_callable=AsyncMock,
        return_value=SessionStatus(datetime(2026, 3, 15, 6, 0, tzinfo=UTC), None),
    )
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_no_callback_is_noop(self, mock_build_prompt, _mock_check):
        mock_build_prompt.return_value = "<race_window>test</race_window>"
        agent = AsyncMock()
        agent.run_stream = MagicMock(return_value=_make_stream_result("Text."))
        embedding_client = AsyncMock()
        embedding_client.embed = AsyncMock(return_value=[0.0] * 1536)

        factory, session = _make_session_factory(datetime(2026, 3, 15, 6, 0, tzinfo=UTC))

        loop = SummarisationLoop(
            session_factory=factory,
            agent=agent,
            embedding_client=embedding_client,
            client=MagicMock(spec=OpenF1Client),
            session_key=12345,
            on_summary=None,
        )

        ended = await loop.summarise_once()
        assert ended is False
        session.commit.assert_awaited_once()
