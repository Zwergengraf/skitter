from __future__ import annotations

from fastapi import FastAPI

from ..core.events import EventBus
from ..core.runtime import AgentRuntime
from ..core.graph import build_graph
from ..core.scheduler import SchedulerService
from ..observability.logging import configure_logging
from ..tools.approval_service import ToolApprovalService
from .routes import artifacts, events, memory, messages, sessions, skills, tools


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Skittermander API", version="0.1.0")

    app.state.event_bus = EventBus()
    app.state.approval_service = ToolApprovalService(app.state.event_bus)
    app.state.runtime = AgentRuntime(app.state.event_bus, approval_service=app.state.approval_service)
    app.state.scheduler_service = SchedulerService(app.state.runtime)
    app.state.runtime.graph = build_graph(
        approval_service=app.state.approval_service, scheduler_service=app.state.scheduler_service
    )

    app.include_router(sessions.router)
    app.include_router(messages.router)
    app.include_router(events.router)
    app.include_router(tools.router)
    app.include_router(skills.router)
    app.include_router(memory.router)
    app.include_router(artifacts.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
