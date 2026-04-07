# Skitter

Skitter is a self-hosted AI operator platform with long-lived memory, tool use, schedules, background jobs, profile-based agents, and transport-aware routing.

[View on GitHub](https://github.com/Zwergengraf/skitter){ .md-button }

---

## What Skitter Gives You

- One human `User` can own multiple `AgentProfile`s.
- Each profile has its own workspace, sessions, memory, secrets, schedules, and defaults.
- Clients can select different active profiles at the same time.
- Discord supports a shared default bot from `config.yaml` and dedicated per-profile bot overrides.
- Public Discord channels are supported through explicit channel bindings.
- Tool runs, jobs, heartbeats, and schedules can route through the correct transport account.
- Docker sandboxes and external executor nodes can execute tool work with approval and tracing.

## Choose Your Path

=== "Quickstart using Docker"

    - Use [Docker Compose](getting-started/docker-compose.md)
    - Learn login flow in [Auth and Pairing](getting-started/auth-and-pairing.md)
    - Set up Discord in [Discord Transport](components/discord-transport.md)
    - Explore workflows in [Patterns](patterns/overview.md)

=== "I Want to Self-Host Skitter"

    - Use the [Manual Setup](getting-started/manual-setup.md)
    - Configure models, workspace roots, and Discord defaults in [Configuration](getting-started/configuration.md)
    - Check health and operations in [Operations](operations/deployment.md)

=== "I Want to Extend Skitter"

    - Read [System Overview](architecture/system-overview.md)
    - Read [Profiles and Transports](core-concepts/profiles-and-transports.md)
    - Add capabilities with [Skills](core-concepts/skills.md)
    - Integrate machine routing in [Executors](api/executors.md)

---

!!! tip "Recommended First 30 Minutes"
    1. Run [Manual Setup](getting-started/manual-setup.md) or [Docker Compose](getting-started/docker-compose.md).
    2. Pair one additional client.
    3. Create a second profile and switch to it in one client.
    4. If you use Discord, bind one test server channel in the admin web UI.
    5. Run `/model`, `/tools`, and create one scheduled task.
