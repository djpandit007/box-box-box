import httpx
import pytest

from boxboxbox.ingestion.client import OpenF1Client


class TestFixtureParsing:
    def test_sessions_fixture_has_expected_keys(self, load_fixture):
        sessions = load_fixture("sessions")
        assert len(sessions) >= 1
        s = sessions[0]
        assert "session_key" in s
        assert "session_name" in s
        assert "session_type" in s
        assert "circuit_short_name" in s

    def test_drivers_fixture_has_expected_keys(self, load_fixture):
        drivers = load_fixture("drivers")
        assert len(drivers) >= 1
        d = drivers[0]
        assert "driver_number" in d
        assert "full_name" in d
        assert "team_name" in d

    def test_race_control_fixture_has_expected_keys(self, load_fixture):
        events = load_fixture("race_control")
        assert len(events) >= 1
        e = events[0]
        assert "date" in e

    def test_position_fixture_has_expected_keys(self, load_fixture):
        positions = load_fixture("position")
        assert len(positions) >= 1
        p = positions[0]
        assert "driver_number" in p
        assert "position" in p
        assert "date" in p


class TestHashEvent:
    def test_determinism(self):
        data = {"a": 1, "b": "hello", "c": [1, 2, 3]}
        assert OpenF1Client.hash_event(data) == OpenF1Client.hash_event(data)

    def test_key_order_irrelevant(self):
        data1 = {"a": 1, "b": 2}
        data2 = {"b": 2, "a": 1}
        assert OpenF1Client.hash_event(data1) == OpenF1Client.hash_event(data2)

    def test_different_data_different_hash(self):
        data1 = {"a": 1}
        data2 = {"a": 2}
        assert OpenF1Client.hash_event(data1) != OpenF1Client.hash_event(data2)


class TestClientGet:
    @pytest.mark.asyncio
    async def test_get_with_mock_transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"session_key": 123}])

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as mock_client:
            client = OpenF1Client("http://test")
            client._client = mock_client
            result = await client.get("/sessions", {"session_key": "latest"})
            assert result == [{"session_key": 123}]
