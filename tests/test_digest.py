from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from boxboxbox.models import Session, Summary
from boxboxbox.summariser.digest import _build_digest_prompt, generate_digest


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


def _make_summary(window_start: str, window_end: str, text: str) -> Summary:
    s = MagicMock(spec=Summary)
    s.window_start = datetime.fromisoformat(window_start)
    s.window_end = datetime.fromisoformat(window_end)
    s.summary_text = text
    return s


def _make_session(name: str = "Race", circuit: str = "Monza", session_type: str = "Race") -> Session:
    s = MagicMock(spec=Session)
    s.session_name = name
    s.circuit_short_name = circuit
    s.session_type = session_type
    return s


class TestBuildDigestPrompt:
    def test_includes_all_summaries(self):
        summaries = [
            _make_summary("2026-03-15T06:20:00", "2026-03-15T06:21:00", "Hamilton leads after lap 1."),
            _make_summary("2026-03-15T06:21:00", "2026-03-15T06:22:00", "Verstappen pits for hards."),
        ]
        session = _make_session("Australian Grand Prix", "Melbourne")

        prompt = _build_digest_prompt(summaries, session)

        assert "<race_summaries" in prompt
        assert 'session="Australian Grand Prix"' in prompt
        assert 'circuit="Melbourne"' in prompt
        assert "Hamilton leads after lap 1." in prompt
        assert "Verstappen pits for hards." in prompt
        assert prompt.count("<summary") == 2

    def test_includes_window_timestamps(self):
        summaries = [_make_summary("2026-03-15T06:20:00", "2026-03-15T06:21:00", "Test summary.")]
        prompt = _build_digest_prompt(summaries, _make_session())
        assert 'window="06:20:00-06:21:00"' in prompt

    def test_handles_none_session(self):
        summaries = [_make_summary("2026-03-15T06:20:00", "2026-03-15T06:21:00", "Test.")]
        prompt = _build_digest_prompt(summaries, None)
        assert 'session="Unknown"' in prompt
        assert 'circuit="Unknown"' in prompt


class TestGenerateDigest:
    @pytest.mark.asyncio
    async def test_generates_and_stores_digest(self):
        # Mock agent
        agent = AsyncMock()
        output_text = (
            "Lead: [dramatic] A thrilling race saw Hamilton take victory after a masterful strategy call.\n"
            "Analyst: [analytical] The undercut was the decisive moment of the afternoon."
        )
        agent.run_stream = MagicMock(return_value=_make_stream_result(output_text))

        # Mock embedding client
        embedding_client = AsyncMock()
        embedding_client.embed = AsyncMock(return_value=[0.0] * 1536)

        # Mock DB session with summaries
        summary1 = _make_summary("2026-03-15T06:20:00", "2026-03-15T06:21:00", "Summary 1")
        summary2 = _make_summary("2026-03-15T06:21:00", "2026-03-15T06:22:00", "Summary 2")

        session_obj = _make_session("Race", "Melbourne")

        no_existing_digest = MagicMock()
        no_existing_digest.scalar_one_or_none.return_value = None

        summaries_result = MagicMock()
        summaries_result.scalars.return_value.all.return_value = [summary1, summary2]

        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = session_obj

        standings_result = MagicMock()
        standings_result.scalars.return_value.all.return_value = []

        driver_result = MagicMock()
        driver_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[no_existing_digest, summaries_result, session_result, standings_result, driver_result]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()

        factory_cm = AsyncMock()
        factory_cm.__aenter__ = AsyncMock(return_value=db)
        factory_cm.__aexit__ = AsyncMock(return_value=False)

        def make_session():
            return factory_cm

        with patch("boxboxbox.summariser.digest.generate_audio", new_callable=AsyncMock) as mock_audio:
            mock_audio.return_value = None
            result = await generate_digest(make_session, agent, embedding_client, 12345)

        assert result == output_text
        agent.run_stream.assert_called_once()
        embedding_client.embed.assert_called_once()
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_summaries(self):
        agent = AsyncMock()
        embedding_client = AsyncMock()

        no_existing_digest = MagicMock()
        no_existing_digest.scalar_one_or_none.return_value = None

        summaries_result = MagicMock()
        summaries_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[no_existing_digest, summaries_result])

        factory_cm = AsyncMock()
        factory_cm.__aenter__ = AsyncMock(return_value=db)
        factory_cm.__aexit__ = AsyncMock(return_value=False)

        def make_session():
            return factory_cm

        result = await generate_digest(make_session, agent, embedding_client, 12345)

        assert result == ""
        agent.run_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_reuses_existing_digest_with_audio(self):
        agent = AsyncMock()
        embedding_client = AsyncMock()

        existing = MagicMock(spec=Summary)
        existing.summary_text = "Existing digest text."
        existing.audio_url = "/audio/digest_12345.mp3"

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=existing_result)

        factory_cm = AsyncMock()
        factory_cm.__aenter__ = AsyncMock(return_value=db)
        factory_cm.__aexit__ = AsyncMock(return_value=False)

        result = await generate_digest(lambda: factory_cm, agent, embedding_client, 12345)

        assert result == "Existing digest text."
        agent.run_stream.assert_not_called()
        embedding_client.embed.assert_not_called()
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_generates_audio_for_existing_digest_without_audio(self):
        agent = AsyncMock()
        embedding_client = AsyncMock()

        existing = MagicMock(spec=Summary)
        existing.summary_text = "Existing digest text."
        existing.audio_url = None

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=existing_result)
        db.commit = AsyncMock()

        factory_cm = AsyncMock()
        factory_cm.__aenter__ = AsyncMock(return_value=db)
        factory_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("boxboxbox.summariser.digest.generate_audio", new_callable=AsyncMock) as mock_audio:
            mock_audio.return_value = "/audio/digest_12345.mp3"
            result = await generate_digest(lambda: factory_cm, agent, embedding_client, 12345)

        assert result == "Existing digest text."
        agent.run_stream.assert_not_called()
        embedding_client.embed.assert_not_called()
        db.add.assert_not_called()
        mock_audio.assert_called_once_with("Existing digest text.", 12345, "Race")
        db.commit.assert_called_once()
