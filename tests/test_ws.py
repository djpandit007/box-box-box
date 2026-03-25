from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from boxboxbox.delivery.ws import ConnectionManager


def _make_ws(fail_on_send: bool = False) -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    if fail_on_send:
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
    else:
        ws.send_text = AsyncMock()
    return ws


class TestConnectionManager:
    @pytest.mark.asyncio
    async def test_connect_accepts_and_adds(self):
        manager = ConnectionManager()
        ws = _make_ws()
        await manager.connect(ws)
        ws.accept.assert_awaited_once()
        assert ws in manager._connections

    @pytest.mark.asyncio
    async def test_disconnect_removes(self):
        manager = ConnectionManager()
        ws = _make_ws()
        await manager.connect(ws)
        manager.disconnect(ws)
        assert ws not in manager._connections

    @pytest.mark.asyncio
    async def test_disconnect_unknown_is_noop(self):
        manager = ConnectionManager()
        ws = _make_ws()
        manager.disconnect(ws)  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast_html_wraps_in_type_html(self):
        manager = ConnectionManager()
        ws = _make_ws()
        await manager.connect(ws)
        await manager.broadcast_html("<p>hello</p>")
        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "html"
        assert payload["html"] == "<p>hello</p>"

    @pytest.mark.asyncio
    async def test_broadcast_json_wraps_in_type_snapshot(self):
        manager = ConnectionManager()
        ws = _make_ws()
        await manager.connect(ws)
        data = {"positions": [{"driver_number": 1, "position": 1}], "intervals": [], "weather": {"rainfall": 0}}
        await manager.broadcast_json(data)
        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["type"] == "snapshot"
        assert payload["positions"] == data["positions"]

    @pytest.mark.asyncio
    async def test_dead_socket_removed_on_send_failure(self):
        manager = ConnectionManager()
        good_ws = _make_ws()
        bad_ws = _make_ws(fail_on_send=True)
        await manager.connect(good_ws)
        await manager.connect(bad_ws)
        await manager.broadcast_html("<p>test</p>")
        assert bad_ws not in manager._connections
        assert good_ws in manager._connections

    @pytest.mark.asyncio
    async def test_broadcast_reaches_multiple_connections(self):
        manager = ConnectionManager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        await manager.connect(ws1)
        await manager.connect(ws2)
        await manager.broadcast_html("<p>multi</p>")
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
