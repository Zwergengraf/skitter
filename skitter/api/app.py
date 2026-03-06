from __future__ import annotations

import logging
import secrets as stdlib_secrets
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..core.events import EventBus
from ..core.runtime import AgentRuntime
from ..core.scheduler import SchedulerService
from ..core.config import settings
from ..core.llm import invalid_model_selectors, list_models
from ..core.mcp import mcp_registry
from ..data.db import SessionLocal
from ..data.repositories import Repository
from ..observability.logging import configure_logging
from ..tools.approval_service import ToolApprovalService
from ..tools.sandbox_manager import sandbox_manager
from .security import AuthPrincipal, extract_credential, hash_secret, utcnow
from .routes import (
    agent_jobs,
    auth,
    channels,
    commands,
    config,
    executors,
    events,
    memory,
    mcp,
    messages,
    models,
    overview,
    runs,
    sandbox,
    schedules,
    secrets,
    sessions,
    skills,
    tools,
    users,
)

_logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Skitter API", version="0.1.0")
    invalid_selectors = invalid_model_selectors()
    if invalid_selectors:
        available_models = ", ".join(model.name for model in list_models()) or "(none configured)"
        for field, selectors in invalid_selectors.items():
            _logger.warning(
                "Invalid model selectors in %s: %s. Available models: %s",
                field,
                ", ".join(selectors),
                available_models,
            )
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
    app.state.job_service = None
    app.state.user_notifier = None
    app.state.started_at = datetime.utcnow()

    app.state.runtime.ready = True

    @app.middleware("http")
    async def _api_key_guard(request, call_next):
        request.state.auth_principal = None
        if request.url.path.startswith("/v1/"):
            # Allow CORS preflight through without auth headers.
            if request.method.upper() != "OPTIONS":
                path = request.url.path
                anonymous_allowed = {
                    "/v1/auth/bootstrap",
                    "/v1/auth/pair/complete",
                }
                if path not in anonymous_allowed:
                    provided = extract_credential(request)
                    if not provided:
                        return JSONResponse(status_code=401, content={"detail": "Missing authentication credential."})
                    expected_admin = settings.api_key.strip()
                    if expected_admin and stdlib_secrets.compare_digest(provided, expected_admin):
                        request.state.auth_principal = AuthPrincipal(kind="admin")
                    else:
                        hashed = hash_secret(provided)
                        async with SessionLocal() as session:
                            repo = Repository(session)
                            token = await repo.get_auth_token_by_hash(hashed)
                            if token is None:
                                return JSONResponse(status_code=401, content={"detail": "Invalid authentication token."})
                            if token.revoked_at is not None:
                                return JSONResponse(status_code=401, content={"detail": "Authentication token has been revoked."})
                            now = utcnow()
                            if token.expires_at is not None and token.expires_at <= now:
                                return JSONResponse(status_code=401, content={"detail": "Authentication token has expired."})
                            request.state.auth_principal = AuthPrincipal(
                                kind="user",
                                user_id=token.user_id,
                                token_id=token.id,
                            )
                            await repo.touch_auth_token(token)
        return await call_next(request)

    @app.on_event("startup")
    async def _start_sandbox_manager() -> None:
        if sandbox_manager is not None:
            await sandbox_manager.start()

    @app.on_event("shutdown")
    async def _stop_mcp_registry() -> None:
        await mcp_registry.shutdown()

    app.include_router(sessions.router)
    app.include_router(auth.router)
    app.include_router(commands.router)
    app.include_router(messages.router)
    app.include_router(events.router)
    app.include_router(tools.router)
    app.include_router(agent_jobs.router)
    app.include_router(runs.router)
    app.include_router(skills.router)
    app.include_router(models.router)
    app.include_router(secrets.router)
    app.include_router(memory.router)
    app.include_router(mcp.router)
    app.include_router(overview.router)
    app.include_router(schedules.router)
    app.include_router(users.router)
    app.include_router(channels.router)
    app.include_router(sandbox.router)
    app.include_router(executors.router)
    app.include_router(config.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
