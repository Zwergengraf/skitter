from __future__ import annotations

import secrets as stdlib_secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..core.events import EventBus
from ..core.runtime import AgentRuntime
from ..core.scheduler import SchedulerService
from ..core.config import settings
from ..observability.logging import configure_logging
from ..tools.approval_service import ToolApprovalService
from ..tools.sandbox_manager import sandbox_manager
from .routes import channels, events, memory, messages, overview, schedules, sessions, skills, tools, users, sandbox, config, secrets, models


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Skittermander API", version="0.1.0")
    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.event_bus = EventBus()
    app.state.approval_service = ToolApprovalService(app.state.event_bus)
    app.state.runtime = AgentRuntime(app.state.event_bus, approval_service=app.state.approval_service)
    app.state.scheduler_service = SchedulerService(app.state.runtime)
    app.state.runtime.set_scheduler_service(app.state.scheduler_service)
    app.state.user_notifier = None

    app.state.runtime.ready = True

    @app.middleware("http")
    async def _api_key_guard(request, call_next):
        if request.url.path.startswith("/v1/"):
            # Allow CORS preflight through without auth headers.
            if request.method.upper() != "OPTIONS":
                expected = settings.api_key.strip()
                if not expected:
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "API key auth is enabled but SKITTER_API_KEY is not configured."},
                    )
                provided = (request.headers.get("x-api-key") or "").strip()
                if not provided:
                    auth_header = (request.headers.get("authorization") or "").strip()
                    if auth_header.lower().startswith("bearer "):
                        provided = auth_header[7:].strip()
                if not provided or not stdlib_secrets.compare_digest(provided, expected):
                    return JSONResponse(status_code=401, content={"detail": "Invalid API key."})
        return await call_next(request)

    @app.on_event("startup")
    async def _start_sandbox_manager() -> None:
        if sandbox_manager is not None:
            await sandbox_manager.start()

    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(events.router)
    app.include_router(tools.router)
    app.include_router(skills.router)
    app.include_router(models.router)
    app.include_router(secrets.router)
    app.include_router(memory.router)
    app.include_router(overview.router)
    app.include_router(schedules.router)
    app.include_router(users.router)
    app.include_router(channels.router)
    app.include_router(sandbox.router)
    app.include_router(config.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
