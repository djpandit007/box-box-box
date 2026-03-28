from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_SECONDS = 30


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("WebSocket connected; total=%d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("WebSocket disconnected; total=%d", len(self._connections))

    async def broadcast_html(self, html: str) -> None:
        await self._broadcast({"type": "html", "html": html})

    async def broadcast_json(self, data: dict) -> None:
        await self._broadcast({"type": "snapshot", **data})

    async def _broadcast(self, message: dict) -> None:
        dead: set[WebSocket] = set()
        text = json.dumps(message)
        for ws in list(self._connections):
            try:
                await ws.send_text(text)
            except Exception:
                logger.warning("Failed to send to WebSocket; removing dead connection")
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)
