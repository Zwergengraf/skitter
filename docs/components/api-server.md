# API Server

The API server is the main orchestration process in Skitter.

## Responsibilities

- auth and route guards
- runtime wiring
- scheduler, heartbeat, and job service startup
- transport account reconciliation
- profile-aware session resolution
- event streaming and run tracing

## Important Runtime Wiring

At startup the API server wires:

- `AgentRuntime`
- `SchedulerService`
- `HeartbeatService`
- `JobService`
- `TransportManager`
- `SessionRunQueue`

The `SessionRunQueue` is what serializes one active run per session and enables backlog coalescing for busy public Discord sessions.
