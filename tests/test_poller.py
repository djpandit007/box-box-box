from unittest.mock import AsyncMock

import pytest

from boxboxbox.ingestion.endpoints import ENDPOINTS, Priority
from boxboxbox.ingestion.poller import Poller


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    factory = AsyncMock(return_value=session)
    factory.return_value = session
    # Make the factory callable and return the mock session as a context manager
    factory_cm = AsyncMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)

    def make_session():
        return factory_cm

    return make_session


class TestTickRouting:
    def test_tick_1_polls_p1_only(self, mock_client, mock_session_factory):
        poller = Poller(mock_client, mock_session_factory)
        poller._tick = 0  # will become 1 after increment

        # Simulate what poll_once does: increment then check
        poller._tick = 1
        for ep in ENDPOINTS:
            if ep.priority == Priority.P1:
                assert poller._should_poll(ep), f"{ep.name} should be polled on tick 1"
            else:
                assert not poller._should_poll(ep), f"{ep.name} should NOT be polled on tick 1"

    def test_tick_3_polls_p1_and_p2(self, mock_client, mock_session_factory):
        poller = Poller(mock_client, mock_session_factory)
        poller._tick = 3

        for ep in ENDPOINTS:
            if ep.priority in (Priority.P1, Priority.P2):
                assert poller._should_poll(ep), f"{ep.name} should be polled on tick 3"
            else:
                assert not poller._should_poll(ep), f"{ep.name} should NOT be polled on tick 3"

    def test_tick_6_polls_all(self, mock_client, mock_session_factory):
        poller = Poller(mock_client, mock_session_factory)
        poller._tick = 6

        for ep in ENDPOINTS:
            assert poller._should_poll(ep), f"{ep.name} should be polled on tick 6"

    def test_tick_12_polls_all(self, mock_client, mock_session_factory):
        poller = Poller(mock_client, mock_session_factory)
        poller._tick = 12

        for ep in ENDPOINTS:
            assert poller._should_poll(ep), f"{ep.name} should be polled on tick 12"

    def test_tick_4_polls_p1_only(self, mock_client, mock_session_factory):
        poller = Poller(mock_client, mock_session_factory)
        poller._tick = 4

        for ep in ENDPOINTS:
            if ep.priority == Priority.P1:
                assert poller._should_poll(ep)
            else:
                assert not poller._should_poll(ep)


class TestIncrementalDateTracking:
    @pytest.mark.asyncio
    async def test_last_dates_updated_after_fetch(self, mock_client, mock_session_factory):
        mock_client.get.return_value = [
            {
                "date": "2025-03-16T14:00:00",
                "message": "GREEN LIGHT",
                "meeting_key": 1,
                "session_key": 12345,
                "category": "Flag",
            },
            {
                "date": "2025-03-16T14:01:00",
                "message": "YELLOW FLAG",
                "meeting_key": 1,
                "session_key": 12345,
                "category": "Flag",
            },
        ]

        poller = Poller(mock_client, mock_session_factory)
        poller._session_key = 12345

        from boxboxbox.ingestion.endpoints import EndpointConfig, Priority

        ep = EndpointConfig("race_control", "/race_control", Priority.P1)
        await poller._fetch_and_store(ep)

        assert poller._last_dates["race_control"] == "2025-03-16T14:01:00"
