from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boxboxbox.summariser.loop import SummarisationLoop, generate_historical_summaries


def _make_stream_result(text: str):
    """Create a mock that works as `async with agent.run_stream() as result`."""
    stream_result = AsyncMock()

    async def _stream_text(delta=False):
        yield text

    stream_result.stream_text = _stream_text
    stream_result.get_output = AsyncMock(return_value=text)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=stream_result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    output_text = "Hamilton takes the lead after a brilliant overtake on Verstappen."
    agent.run_stream = MagicMock(return_value=_make_stream_result(output_text))
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
        mock_agent.run_stream.assert_called_once()
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
        mock_agent.run_stream.assert_not_called()
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


class TestGenerateHistoricalSummariesResume:
    @pytest.mark.asyncio
    async def test_second_run_reuses_existing_without_llm_call(self):
        agent = AsyncMock()
        agent.run_stream = MagicMock(return_value=_make_stream_result("New summary"))

        embedding_client = AsyncMock()
        embedding_client.embed = AsyncMock(return_value=[0.0] * 1536)

        # First run: DB has events but no existing summaries, and no explicit race_start.
        min_max_result_1 = MagicMock()
        min_max_result_1.one.return_value = (
            datetime(2026, 3, 15, 6, 0, tzinfo=UTC),
            datetime(2026, 3, 15, 6, 1, tzinfo=UTC),
        )

        # Session.date_start lookup should return None for this test.
        session_date_result_1 = MagicMock()
        session_date_result_1.scalar_one_or_none.return_value = None

        existing_empty_result = MagicMock()
        existing_empty_result.scalars.return_value.all.return_value = []

        # Second run: DB has same events and one existing summary covering the whole range.
        min_max_result_2 = MagicMock()
        min_max_result_2.one.return_value = min_max_result_1.one.return_value

        # Session.date_start lookup again returns None.
        session_date_result_2 = MagicMock()
        session_date_result_2.scalar_one_or_none.return_value = None

        existing_one = MagicMock()
        existing_one.window_start = datetime(2026, 3, 15, 6, 0, tzinfo=UTC)
        existing_one.window_end = datetime(2026, 3, 15, 6, 1, tzinfo=UTC)
        existing_one.summary_text = "Existing summary"

        existing_one_result = MagicMock()
        existing_one_result.scalars.return_value.all.return_value = [existing_one]

        # generate_historical_summaries does three queries during initialisation:
        # 1) min/max event dates
        # 2) Session.date_start
        # 3) existing window summaries
        db1_init = AsyncMock()
        db1_init.execute = AsyncMock(side_effect=[min_max_result_1, session_date_result_1, existing_empty_result])

        db1_loop = AsyncMock()
        db1_loop.add = MagicMock()
        db1_loop.commit = AsyncMock()

        db2_init = AsyncMock()
        db2_init.execute = AsyncMock(side_effect=[min_max_result_2, session_date_result_2, existing_one_result])

        cm1_init = AsyncMock()
        cm1_init.__aenter__ = AsyncMock(return_value=db1_init)
        cm1_init.__aexit__ = AsyncMock(return_value=False)

        cm1_loop = AsyncMock()
        cm1_loop.__aenter__ = AsyncMock(return_value=db1_loop)
        cm1_loop.__aexit__ = AsyncMock(return_value=False)

        cm2_init = AsyncMock()
        cm2_init.__aenter__ = AsyncMock(return_value=db2_init)
        cm2_init.__aexit__ = AsyncMock(return_value=False)

        cms = [cm1_init, cm1_loop, cm2_init]
        call_count = 0

        def make_session():
            nonlocal call_count
            call_count += 1
            return cms[call_count - 1]

        with patch("boxboxbox.summariser.loop.build_prompt", new=AsyncMock(return_value="<race_window/>")):
            await generate_historical_summaries(
                session_factory=make_session,
                agent=agent,
                embedding_client=embedding_client,
                session_key=12345,
                interval_seconds=60,
            )
            agent.run_stream.reset_mock()
            await generate_historical_summaries(
                session_factory=make_session,
                agent=agent,
                embedding_client=embedding_client,
                session_key=12345,
                interval_seconds=60,
            )

        # If we are correctly reusing existing summaries on the second run, there should be no LLM calls.
        agent.run_stream.assert_not_called()
