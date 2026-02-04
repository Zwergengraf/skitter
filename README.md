# Skittermander

Python backend for an AI assistant with pluggable transports (Discord, Web, CLI), tool sandboxing, and a companion API.

## Quickstart (dev)

1. Create a virtual environment and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Start Postgres (with pgvector) and the sandbox runner:

```bash
docker compose up -d
```

3. Initialize the database schema:

```bash
python -m skittermander.data.init_db
```

4. Set environment variables:

```
SKITTER_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/skittermander
SKITTER_OPENAI_API_BASE=https://api.openai.com/v1
SKITTER_OPENAI_API_KEY=your_key
SKITTER_DISCORD_TOKEN=your_discord_bot_token
SKITTER_WORKSPACE_ROOT=workspace
SKITTER_EMBEDDINGS_API_BASE=http://localhost:11434/v1
SKITTER_EMBEDDINGS_API_KEY=
SKITTER_EMBEDDINGS_MODEL=text-embedding-3-small
SKITTER_EMBEDDINGS_MAX_CHUNK_CHARS=800
SKITTER_MEMORY_MIN_SIMILARITY=0.3
SKITTER_BRAVE_API_KEY=
SKITTER_BRAVE_API_BASE=https://api.search.brave.com/res/v1/web/search
SKITTER_BROWSER_EXECUTABLE=/usr/bin/brave-browser
SKITTER_SCHEDULER_TIMEZONE=UTC
```

5. Run the API:

```bash
uvicorn skittermander.api.app:create_app --factory --reload
```

6. Run the Discord bot (optional):

```bash
python -m skittermander.transports.discord
```

## Tool approval (human-in-the-loop)

Set which tools require approval (comma-separated):

```
SKITTER_TOOL_APPROVAL_TOOLS=filesystem,browser,browser_action,sub_agent,shell
```

When a tool requires approval, the Discord bot will send an approval message with Approve/Deny buttons.

## Memory reindex

If you edit or delete files under `workspace/memory`, run the `/memory_reindex` command in Discord to regenerate embeddings.

## Architecture

See `skittermander/` for core modules:

- `core/` agent runtime and skills
- `transports/` message adapters
- `tools/` tool registry and sandbox client
- `sandbox/` dockerized tool runner
- `data/` postgres repositories
- `api/` FastAPI app
- `observability/` logging and metrics
