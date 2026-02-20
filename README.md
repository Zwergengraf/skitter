<h1 align="center">Skitter</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Warning-Vibe_coded-333333?labelColor=cc1111&style=for-the-badge" alt="Vibe coded" /><br />
  Personal AI assistant platform with a Python agent runtime, secure tool sandbox, and multiple client apps.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LangChain%20%2B%20LangGraph-Agent%20Runtime-1C3C3C?style=for-the-badge" alt="LangChain + LangGraph" />
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL + pgvector" />
  <img src="https://img.shields.io/badge/React-Admin%20UI-61DAFB?style=for-the-badge&logo=react&logoColor=111111" alt="React Admin UI" />
  <img src="https://img.shields.io/badge/Textual-TUI-20232A?style=for-the-badge" alt="Textual TUI" />
  <img src="https://img.shields.io/badge/macOS-Swift%20MenuBar-FAFAFA?style=for-the-badge&logo=apple&logoColor=111111" alt="Swift MenuBar App" />
</p>

## What This Is

Skitter is a personal agent system with:

- A Python server (`FastAPI` + `LangGraph`) that runs the assistant.
- Distributed executors for filesystem, shell, browser, and web tools (Docker sandboxes and external node runners).
- Memory indexing and retrieval (PostgreSQL + pgvector).
- Human-in-the-loop approvals for sensitive tools.
- Multiple client apps over one API: Discord bot, admin web UI, standalone TUI, and a native macOS menubar app.

## Applications

| App | Location | Purpose |
| --- | --- | --- |
| Server | `/skitter` | Agent runtime, API, scheduling, heartbeats, tools, memory |
| Admin Web UI | `/admin-web` | Operational dashboard (sessions, tool runs, jobs, memory, sandbox, settings) |
| Standalone TUI | `/skitter-tui` | Remote terminal chat client over API |
| macOS Menubar App | `/skitter-menubar` | Native companion app with quick chat + status |
| Executor Node | `/skitter/node` | External host runner (macOS/Linux) that connects to API via WebSocket |

## Architecture (High Level)

- `skitter/core`: runtime, graph, sessions, memory, scheduler, heartbeats, sub-agents.
- `skitter/api`: `/v1/*` API routes and auth middleware.
- `skitter/tools`: approvals, executor router, docker sandbox manager.
- `skitter/sandbox`: tool runner app used by docker sandbox and external executor node.
- `skitter/node`: external executor process (`skitter-node`).
- `skitter/data`: models, repositories, schema init.
- `workspace-skeleton`: default per-user workspace bootstrap content.

## Prerequisites

- Python `3.11+`
- Node.js `18+` (admin UI)
- Docker (for Postgres + sandbox containers)
- PostgreSQL with pgvector (the provided Docker image includes it)
- macOS 14+ with Swift toolchain (menubar app only)

## Setup

### 1) Clone, install backend, and prepare config

```bash
git clone <your-repo-url>
cd skitter

python -m venv venv
source venv/bin/activate
pip install -e .[dev]

cp config.example.yaml config.yaml
cp .env.example .env
```

### 2) Configure auth, passwords and secrets encryption (env-only)

Generate a valid Fernet key (SKITTER_SECRETS_MASTER_KEY):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set these in `.env`:

```bash
SKITTER_CONFIG_PATH=config.yaml
SKITTER_API_KEY=long-random-admin-key
SKITTER_BOOTSTRAP_CODE=one-time-setup-code
SKITTER_POSTGRES_PASSWORD=secure-postgres-password
SKITTER_SECRETS_MASTER_KEY=fernet-key
```

To generate random strings with openssl:

```bash
openssl rand -hex 24
```

### 3) Configure models and services in `config.yaml`

At minimum, set:

- `providers` (`name`, optional `api_type` = `openai|anthropic`, `api_base`, `api_key`)
- `models` (`name`, `provider`, `model_id`, token costs)
- `main_model` as an ordered array of selectors (`provider/model`)
- `heartbeat_model` as an ordered array of selectors (`provider/model`)
- `database.url` (if not using default)
- `discord.token` (if using Discord transport)

Web search provider config:

- `web_search.engine`: `brave` or `searxng`
- `web_search.brave.api_key` / `web_search.brave.api_base`
- `web_search.searxng.api_base`

`web_search` tool inputs are intentionally minimal: `query` and optional `count`.

### 4) Start infrastructure

Start PostgreSQL (pgvector enabled):

```bash
docker compose up -d postgres
```

Build sandbox image used for per-user Docker executors:

```bash
docker build -f skitter/sandbox/Dockerfile -t skitter-sandbox .
```

If you only use external executor nodes and disable Docker auto-fallback, sandbox image build is optional.

Initialize database schema:

```bash
python -m skitter.data.init_db
```

### 5) Run the server

You can either run the server like this, or in Docker

```bash
python -m skitter.server
```

This starts:

- FastAPI on `http://localhost:8000`
- Discord transport (unless disabled)
- scheduler and heartbeat services

To disable Discord:

```bash
SKITTER_ENABLE_DISCORD=false python -m skitter.server
```

## Docker Compose (DB + API + Admin Web)

Use this when you want core components fully containerized.

### 1) Build all required images (API, Admin Web, Sandbox)

```bash
docker compose --profile sandbox build
```

### 2) Start core services

```bash
docker compose up -d postgres api admin-web
```

Endpoints:

- API: `http://localhost:8000`
- Admin Web UI: `http://localhost:5173`

Notes:

- `api` auto-runs DB initialization on startup (`python -m skitter.data.init_db`).
- `sandbox` image is built but not started as a long-running service. The API spawns per-user sandbox containers on demand via Docker socket access.
- The admin web image is built with `VITE_API_KEY`; this key is embedded in client-side assets. Do not expose this UI publicly without additional auth controls.

Optional: run local SearXNG from this repo:

```bash
docker compose -f searxng/docker-compose.yml up -d
```

Then set in `config.yaml`:

```yaml
web_search:
  engine: searxng
  searxng:
    api_base: http://localhost:8888/search
```

## Executor Workflow

Skitter routes tool execution to an executor per user.

- Docker executor: auto-managed per-user sandbox container (`docker-default`).
- Node executor: external host process (`skitter-node`) connected to API over WebSocket.

Selection behavior:

- User default executor is set manually with `/machine`.
- If no default is set and `executors.auto_docker_default=true`, Docker fallback is used.
- If `executors.auto_docker_default=false`, execution requires an explicit/default non-disabled executor.

### Onboard a node executor (recommended path)

1. Open Admin Web UI → **Executors**.
2. Click **Add executor node** and create token/command.
3. Run generated command on target host (macOS/Linux):

```bash
skitter-node --api-url "http://<api-host>:8000" --token "<token>" --name "<node-name>" --workspace-root "<path>" --write-config
```

4. Node appears online in Executors view once connected.

### Configure executor tool capabilities

`skitter-node` supports per-node tool allowlists in its config file:

```yaml
capabilities:
  tools:
    - read
    - write
    - list
    - shell
```

- Omit `capabilities.tools` to use full default tool set.
- If a tool is not enabled, API requests to that node return a clear error for that tool.
- You can also override from CLI/env:
  - `--tools read,write,list,shell`
  - `SKITTER_NODE_TOOLS=read,write,list,shell`

### Manage executors

- **Disable**: temporarily blocks executor and disconnects active node session.
- **Enable**: re-allows executor.
- **Delete**: permanently removes executor and its tokens.

### Set default machine as user

- Discord: `/machine` (list), `/machine <name_or_id>` (set default).
- TUI: `/machine` / `/machine <name_or_id>`.
- Menubar: `/machine` / `/machine <name_or_id>`.

The agent can inspect machines (`machine_list`, `machine_status`) but cannot change defaults directly.

### About `executor.local` in node logs

You may see logs like:

`POST http://executor.local/execute`

This is an internal in-process ASGI transport base URL used by `skitter-node`, not a real DNS host/network call.

## Run Client Apps

### Admin Web UI (React/Vite)

```bash
cd admin-web
npm install
npm run dev
```

By default Vite runs on `http://localhost:5173`.

### Standalone TUI

```bash
cd skitter-tui
python -m venv .venv
source .venv/bin/activate
pip install -e .

skitter-tui --api-url http://localhost:8000 --access-token <USER_ACCESS_TOKEN>
```

If you do not have a token yet, start TUI and use:

- `/bootstrap <setup_code> <display_name>` for first-time setup
- `/pair <pair_code>` to connect an existing Discord-approved account

### macOS Menubar App

```bash
cd skitter-menubar
swift build
swift run
```

Open app settings and provide:

- API URL
- Access token, or use:
  - Register & Connect (bootstrap code + display name), or
  - Pair Existing Account (pair code)

## API Auth

`/v1/*` uses two auth modes:

1. Admin key (full admin scope):
- `x-api-key: <SKITTER_API_KEY>`
- or `Authorization: Bearer <SKITTER_API_KEY>`

2. User access token (user-scoped):
- `Authorization: Bearer <token>`
- tokens are issued by:
  - `POST /v1/auth/bootstrap` (first device setup using `SKITTER_BOOTSTRAP_CODE`)
  - `POST /v1/auth/pair/complete` (pair code flow)

Anonymous access is only allowed for:
- `POST /v1/auth/bootstrap`
- `POST /v1/auth/pair/complete`

Useful auth endpoints:
- `GET /v1/auth/me`
- `POST /v1/auth/pair-codes` (create pair code from an already-authenticated user token)

## First-Time Account Flows

### A) No Discord (menubar/TUI only)

1. Set `SKITTER_BOOTSTRAP_CODE` in server env.
2. In menubar/TUI, run bootstrap with setup code + display name.
3. Client receives a user access token and connects.

### B) Start from Discord

1. DM the bot once (user is created as pending).
2. Admin approves the user in Admin UI (`Users` page).
3. In Discord, run `/pair` to get a short-lived pair code.
4. Use that code in menubar/TUI pairing flow.

## Data and Workspaces

- Per-user workspace roots live under `workspace/users/<internal_user_id>/`.
- Typical user folders:
  - `memory/`
  - `screenshots/`
  - `skills/`
  - `.browser/`
- Memory embeddings are stored in PostgreSQL (`memory_entries`) using native `vector`.

## Development Notes

- Server config is YAML (`config.yaml`) plus env-only secrets in `.env`.
- Main API app factory: `skitter/api/app.py`
- End-to-end entrypoint: `python -m skitter.server`
- Existing tests are in `skitter/tests`.

## License

MIT (see `pyproject.toml`).
