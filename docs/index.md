# Skitter

Skitter is your personal AI operator that can chat, run tools, automate recurring work, and execute tasks across multiple machines.
Self-hosted, sandboxed executors (Docker), and with human-in-the-loop approval for secret usage.

[View on GitHub](https://github.com/Zwergengraf/skitter){ .md-button }

---

## What Skitter Gives You

- One shared agent session across clients (Discord DM, terminal UI, macOS menubar).
- Real tools: filesystem, shell, browser, web search, memory retrieval.
- Automation: scheduled jobs, heartbeats, and background jobs.
- Execution routing to Docker sandboxes or external executor nodes (macOS/Linux).
- Human control with approvals, secrets management, limits, and run traces.

## Choose Your Path

=== "Quickstart using Docker"

    - Use [Docker Compose](getting-started/docker-compose.md)
    - Learn login flow in [Auth and Pairing](getting-started/auth-and-pairing.md)
    - Explore workflows in [Patterns](patterns/overview.md)

=== "I Want to Self-Host Skitter"

    - Use the [Manual Setup](getting-started/manual-setup.md)
    - Configure models/executors in [Configuration](getting-started/configuration.md)
    - Check health and operations in [Operations](operations/deployment.md)

=== "I Want to Extend Skitter"

    - Read [System Overview](architecture/system-overview.md)
    - Add capabilities with [Skills](core-concepts/skills.md)
    - Integrate machine routing in [Executors](api/executors.md)

---

!!! tip "Recommended First 30 Minutes"
    1. Run [Manual Setup](getting-started/manual-setup.md).
    2. Pair one additional client (for example menubar + TUI).
    3. Run `/model`, `/tools`, and create one scheduled task.
    4. Open the admin web UI and inspect run traces and tool runs.
