"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paperforge.config import get_config
from paperforge.orchestrator.events import get_event_manager
from paperforge.sandbox.docker_runner import DockerSandboxManager, docker_available
from paperforge.sandbox.monitor import start_monitor, stop_monitor
from paperforge.storage.db import get_storage, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database, orchestrator, and sandbox monitor on startup."""
    cfg = get_config()
    init_db()
    app.state.config = cfg
    app.state.storage = get_storage()
    app.state.event_manager = get_event_manager()

    # Start sandbox monitor
    if docker_available():
        manager = DockerSandboxManager(storage=app.state.storage)
        app.state.sandbox_manager = manager
        await start_monitor(manager)
        app.state.monitor = True
    else:
        app.state.sandbox_manager = None
        app.state.monitor = False

    yield

    # Cleanup
    await stop_monitor()
    if hasattr(app.state, "sandbox_manager") and app.state.sandbox_manager:
        await app.state.sandbox_manager.shutdown_all()


def create_app() -> FastAPI:
    """Application factory."""
    logging.basicConfig(level=logging.INFO)

    cfg = get_config()
    app = FastAPI(
        title="PaperForge API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from api.routes import runs, messages, events, library, sandboxes, preview, files, settings

    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(messages.router, prefix="/api/runs", tags=["messages"])
    app.include_router(events.router, prefix="/api/runs", tags=["events"])
    app.include_router(library.router, prefix="/api/library", tags=["library"])
    app.include_router(sandboxes.router, prefix="/api/sandboxes", tags=["sandboxes"])
    app.include_router(preview.router, prefix="/api/preview", tags=["preview"])
    app.include_router(files.router, prefix="/api/files", tags=["files"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    return app


app = create_app()
