# Overview

Skitter is a personal AI agent platform: chat with your agent, let it use tools and skills, run automations, and execute tasks across your machines from one shared session.

## What Skitter Is

Skitter combines an LLM runtime, tool execution, [Agent Skills](https://agentskills.io/), memory, scheduling, and client apps into one system.  

You can use it like a chat assistant, or as a (semi-)autonomous operator that can run jobs, use browsers, work with files, and report back with results.
The agent can also proactively pull in data (emails, news, changes on your Kanban board, ...) regularly and act accordingly.
Skitter is intended to be lightweight and extensible, so the available features, tools and skills stay easy to use for both humans and agents.
We suggest using Skitter in combination with 
Check the [Patterns](../patterns/overview.md) section for integration ideas and use cases.

## What You Can Do With It

- Run a daily briefing every morning (news, open tasks, pending approvals).
- Start long-running tasks in the background and get notified when they finish.
- Route work to different executors (Docker sandbox, MacBook node, Linux node).
- Let the agent use files, shell commands, browser automation, web search, and memory retrieval.
- Keep one private session across clients (Discord DM, TUI, menubar) so context stays consistent.

## Typical Use Cases

- Personal chief-of-staff workflows (planning, reminders, follow-ups).
- Research and summarization pipelines with scheduled runs.
- Task-board execution loops (for example Trello/Jira via skills).
- Multi-machine automation where specific tasks must run on specific hosts.

## What’s Included

- API server (`FastAPI` + `LangGraph`) for runtime orchestration.
- Tooling layer with approvals, secrets, and run limits.
- Executors:
  - Docker executors (auto-managed, per-user).
  - External node executors (`skitter-node`) on macOS/Linux.
- Clients:
  - Discord (DM-only),
  - Terminal UI (`skitter-tui`),
  - macOS menubar app (`skitter-menubar`).
- Admin web UI for sessions, tool runs, jobs, users, config, and system state.

## Why It Feels Different

- It is stateful: sessions, memory, jobs, and approvals are persisted.
- It is controllable: you set limits, approval rules, and model/provider routing.
- It is extensible: skills and executor nodes let you grow capabilities without rewriting core runtime logic.

## Next Steps

- Fast local setup: [Manual Setup](manual-setup.md)
- Containerized core stack: [Docker Compose](docker-compose.md)
- Configuration reference: [Configuration](configuration.md)
