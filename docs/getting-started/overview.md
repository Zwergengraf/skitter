# Overview

Skitter is a stateful AI agent platform with profiles, tools, schedules, jobs, transport integrations, and persistent workspaces.

## What Skitter Is

Skitter combines:

- an LLM runtime
- profile-scoped workspaces and memory
- tool execution with approvals
- schedules, heartbeats, and background jobs
- multiple client surfaces
- transport-aware delivery

One human account can own multiple agent profiles. Each profile behaves like a distinct agent with its own workspace and long-term context.

## What You Can Do With It

- Keep a default personal profile for daily chat and a second profile for coding, research, or automation.
- Run scheduled jobs and heartbeat checks with profile-specific memory and delivery targets.
- Route tool work to Docker sandboxes or external nodes.
- Use Discord DMs, public Discord channels, TUI, and the macOS menubar app with the same backend.
- Give one profile a dedicated Discord bot while other profiles still use the shared default bot.

## Typical Use Cases

- Personal chief-of-staff workflows.
- Research and summarization pipelines.
- Coding agent workflows with sandboxed execution.
- Multi-profile setups such as `default`, `coder`, and `community-bot`.
- Public Discord channel assistants with mention-gated replies.

## What’s Included

- API server (`FastAPI` + runtime orchestration)
- admin web UI
- profile-aware sessions and memory
- tools, approvals, secrets, and run tracing
- Docker sandbox execution
- external executor nodes
- clients:
  - Discord
  - TUI
  - macOS menubar

## Current Model

- `User` = the human account
- `AgentProfile` = one agent identity and workspace
- `Session` = one conversation thread for one profile
- `TransportAccount` = one bot/account identity for a transport

## Discord in Practice

- The `discord` section in `config.yaml` defines the shared default bot.
- A profile can optionally override that with its own dedicated Discord bot token.
- Public Discord channels are opt-in through channel bindings in the admin web UI.
- Busy public channels are serialized per session and backlog is coalesced into one follow-up turn.

## Next Steps

- [Manual Setup](manual-setup.md)
- [Docker Compose](docker-compose.md)
- [Configuration](configuration.md)
- [Discord Transport](../components/discord-transport.md)
- [Profiles and Transports](../core-concepts/profiles-and-transports.md)
