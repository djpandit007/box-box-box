from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boxboxbox.summariser.loop import SummarisationLoop


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    result = MagicMock()
    result.output = "Hamilton takes the lead after a brilliant overtake on Verstappen."
    agent.run = AsyncMock(return_value=result)
    return agent


@pytest.fixture
def mock_embedding_client():
    client = AsyncMock()
    client.embed = AsyncMock(return_value=[0.0] * 1536)
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    factory_cm = AsyncMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)

    def make_session():
        return factory_cm

    return make_session


class TestSummariseOnce:
    @pytest.mark.asyncio
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_generates_summary_when_events_exist(
        self, mock_build_prompt, mock_agent, mock_embedding_client, mock_session_factory
    ):
        mock_build_prompt.return_value = "<race_window>test prompt</race_window>"

        # Mock _get_previous_summary to return None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        # Mock _earliest_event_date
        earliest_result = MagicMock()
        earliest_result.scalar_one_or_none.return_value = datetime(2026, 3, 15, 6, 0, tzinfo=UTC)

        # Setup execute to return different results for different queries
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.add = MagicMock()
        session.commit = AsyncMock()

        # First call in _earliest_event_date, then in summarise_once (previous_summary + build_prompt)
        session.execute = AsyncMock(side_effect=[mock_result])

        call_count = 0

        def make_session():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # For _earliest_event_date
                cm = AsyncMock()
                cm.__aenter__ = AsyncMock(return_value=AsyncMock(execute=AsyncMock(return_value=earliest_result)))
                cm.__aexit__ = AsyncMock(return_value=False)
                return cm
            # For summarise_once main body
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        loop = SummarisationLoop(
            session_factory=make_session,
            agent=mock_agent,
            embedding_client=mock_embedding_client,
            session_key=12345,
            interval_seconds=60,
            grace_seconds=300,
        )

        ended = await loop.summarise_once()

        assert ended is False
        mock_agent.run.assert_called_once()
        mock_embedding_client.embed.assert_called_once()
        session.add.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_skips_when_no_events(
        self, mock_build_prompt, mock_agent, mock_embedding_client, mock_session_factory
    ):
        mock_build_prompt.return_value = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock(return_value=mock_result)

        call_count = 0

        def make_session():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                earliest_result = MagicMock()
                earliest_result.scalar_one_or_none.return_value = datetime(2026, 3, 15, 6, 0, tzinfo=UTC)
                cm = AsyncMock()
                cm.__aenter__ = AsyncMock(return_value=AsyncMock(execute=AsyncMock(return_value=earliest_result)))
                cm.__aexit__ = AsyncMock(return_value=False)
                return cm
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=session)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        loop = SummarisationLoop(
            session_factory=make_session,
            agent=mock_agent,
            embedding_client=mock_embedding_client,
            session_key=12345,
        )

        ended = await loop.summarise_once()

        assert ended is False
        mock_agent.run.assert_not_called()
        mock_embedding_client.embed.assert_not_called()


class TestSessionEndDetection:
    @pytest.mark.asyncio
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_session_ends_after_grace_period(self, mock_build_prompt, mock_agent, mock_embedding_client):
        mock_build_prompt.return_value = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock(return_value=mock_result)

        def make_session():
            earliest_result = MagicMock()
            earliest_result.scalar_one_or_none.return_value = datetime(2026, 3, 15, 6, 0, tzinfo=UTC)
            cm = AsyncMock()
            inner = AsyncMock()
            inner.execute = AsyncMock(side_effect=[earliest_result, mock_result])
            cm.__aenter__ = AsyncMock(return_value=inner)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        loop = SummarisationLoop(
            session_factory=make_session,
            agent=mock_agent,
            embedding_client=mock_embedding_client,
            session_key=12345,
            grace_seconds=10,
        )

        # First call: sets no_events_since
        ended = await loop.summarise_once()
        assert ended is False

        # Simulate time passing beyond grace period
        loop._no_events_since = datetime.now(UTC) - timedelta(seconds=15)
        ended = await loop.summarise_once()
        assert ended is True


class TestWindowContinuity:
    @pytest.mark.asyncio
    @patch("boxboxbox.summariser.loop.build_prompt")
    async def test_windows_are_contiguous(self, mock_build_prompt, mock_agent, mock_embedding_client):
        mock_build_prompt.return_value = "<race_window>test</race_window>"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock(return_value=mock_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        def make_session():
            cm = AsyncMock()
            inner = AsyncMock()
            earliest_result = MagicMock()
            earliest_result.scalar_one_or_none.return_value = datetime(2026, 3, 15, 6, 0, tzinfo=UTC)
            inner.execute = AsyncMock(return_value=earliest_result)
            inner.add = MagicMock()
            inner.commit = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=inner)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        loop = SummarisationLoop(
            session_factory=make_session,
            agent=mock_agent,
            embedding_client=mock_embedding_client,
            session_key=12345,
        )

        await loop.summarise_once()
        first_window_end = loop._last_window_end
        assert first_window_end is not None

        await loop.summarise_once()
        # The second window should start where the first ended
        # (verified via the build_prompt call args)
        calls = mock_build_prompt.call_args_list
        assert len(calls) == 2
        # Second call's window_start should equal first call's window_end
        # The first call uses earliest_event_date, second uses _last_window_end
        assert calls[1].args[2] == first_window_end  # window_start of second call
