from __future__ import annotations

import pathlib

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from boxboxbox.config import settings
from boxboxbox.delivery.routers import replay, sessions, summaries, standings
from boxboxbox.delivery.ws import ConnectionManager

WEB_HOST = "0.0.0.0"
WEB_PORT = 8000

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"


def create_app(
    session_factory,
    embedding_client,
    manager: ConnectionManager,
    session_key: int,
    *,
    is_live: bool = True,
    session_name: str = "",
    session_type: str = "",
    country_name: str = "",
    circuit_short_name: str = "",
) -> FastAPI:
    app = FastAPI(title="box-box-box")

    app.state.session_factory = session_factory
    app.state.embedding_client = embedding_client
    app.state.manager = manager
    app.state.session_key = session_key
    app.state.is_live = is_live
    app.state.session_name = session_name
    app.state.session_type = session_type
    app.state.country_name = country_name
    app.state.circuit_short_name = circuit_short_name
    app.state.jinja_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), keep_trailing_newline=True)

    app.include_router(sessions.router)
    app.include_router(summaries.router)
    app.include_router(standings.router)
    app.include_router(replay.router)

    # Serve audio files
    audio_dir = pathlib.Path(settings.AUDIO_DIR)
    if audio_dir.is_dir():
        app.mount("/audio", StaticFiles(directory=str(audio_dir)), name="audio")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        template = request.app.state.jinja_env.get_template("base.html")
        return HTMLResponse(
            template.render(
                session_key=request.app.state.session_key,
                is_live=request.app.state.is_live,
                session_name=request.app.state.session_name,
                session_type=request.app.state.session_type,
                country_name=request.app.state.country_name,
                circuit_short_name=request.app.state.circuit_short_name,
            )
        )

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)

    return app
