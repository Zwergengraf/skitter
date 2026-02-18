# Overview

Skitter is a personal AI assistant platform. Use your favorite client (Discord, macOS app, Terminal UI) to chat with your agent, 

## What Skitter Includes

- A Python API/runtime (`FastAPI` + `LangGraph`) that manages sessions, tools, memory, jobs, scheduler, and heartbeats.
- Executor infrastructure to run tools:
  - Docker executors (auto-managed per user, sandboxed)
  - External node executors (`skitter-node`) on macOS/Linux hosts
- Multiple user clients:
  - Discord
  - Terminal UI (`skitter-tui`)
  - Native macOS menubar app (`skitter-menubar`)
- Admin web UI for operations, observability, and configuration.

## Core Concepts You Should Know

- Sessions: one active private session per user.
- Tools: filesystem, shell, browser, memory, web, scheduler, jobs.
- Skills: fully compatible with [Agent Skills](https://agentskills.io/home) to give your agents new capabilities.
- Approvals: configurable human approval flow for sensitive tools or tool calls that use secrets (API keys, passwords, ...).
- Scheduled jobs: automations running on cron or one-shot schedules.
- Background jobs: long-running tasks started by the agent.
- Memory: embeddings-backed retrieval from workspace memory files.
- Heartbeats: regular agent invocations for
- Executors: machine selection and routing for tool execution.

## Next Steps

- If you want a fast local setup: go to [Quickstart](quickstart.md).
- If you want containerized core services: go to [Docker Compose](docker-compose.md).
- If you want details about config keys: go to [Configuration](configuration.md).
