# Skittermander

<p align="center">
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

Skittermander is a personal agent system with:

- A Python server (`FastAPI` + `LangGraph`) that runs the assistant.
- A secure Docker sandbox for filesystem, shell, browser, and web tools.
- Memory indexing and retrieval (PostgreSQL + pgvector).
- Human-in-the-loop approvals for sensitive tools.
- Multiple client apps over one API: Discord bot, admin web UI, standalone TUI, and a native macOS menubar app.

## Applications

| App | Location | Purpose |
| --- | --- | --- |
| Server | `/skittermander` | Agent runtime, API, scheduling, heartbeats, tools, memory |
| Admin Web UI | `/admin-web` | Operational dashboard (sessions, tool runs, jobs, memory, sandbox, settings) |
| Standalone TUI | `/skittermander-tui` | Remote terminal chat client over API |
| macOS Menubar App | `/skittermander-menubar` | Native companion app with quick chat + status |

## Architecture (High Level)

- `skittermander/core`: runtime, graph, sessions, memory, scheduler, heartbeats, sub-agents.
- `skittermander/api`: `/v1/*` API routes and auth middleware.
- `skittermander/tools`: approvals, sandbox client/manager.
- `skittermander/sandbox`: isolated tool runner container.
- `skittermander/data`: models, repositories, schema init.
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
cd Skittermander

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
- `main_model` in `provider/model` format (for example `openai/gpt-5-mini`)
- `heartbeat_model` in `provider/model` format
- `database.url` (if not using default)
- `discord.token` (if using Discord transport)

### 4) Start infrastructure

Start PostgreSQL (pgvector enabled):

```bash
docker compose up -d postgres
```

Build sandbox image used for per-user containers:

```bash
docker build -f skittermander/sandbox/Dockerfile -t skittermander-sandbox .
```

Initialize database schema:

```bash
python -m skittermander.data.init_db
```

### 5) Run the server

You can either run the server like this, or in Docker

```bash
python -m skittermander.server
```

This starts:

- FastAPI on `http://localhost:8000`
- Discord transport (unless disabled)
- scheduler and heartbeat services

To disable Discord:

```bash
SKITTER_ENABLE_DISCORD=false python -m skittermander.server
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

- `api` auto-runs DB initialization on startup (`python -m skittermander.data.init_db`).
- `sandbox` image is built but not started as a long-running service. The API spawns per-user sandbox containers on demand via Docker socket access.
- The admin web image is built with `VITE_API_KEY`; this key is embedded in client-side assets. Do not expose this UI publicly without additional auth controls.

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
cd skittermander-tui
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
cd skittermander-menubar
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
- Main API app factory: `skittermander/api/app.py`
- End-to-end entrypoint: `python -m skittermander.server`
- Existing tests are in `skittermander/tests`.

## License

MIT (see `pyproject.toml`).
