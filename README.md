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
  <img src="https://img.shields.io/badge/iPhone%20%2B%20iPad-SwiftUI%20Client-0A84FF?style=for-the-badge&logo=apple&logoColor=white" alt="iOS SwiftUI App" />
</p>

## What This Is

Skitter is a personal agent system with:

- A Python server (`FastAPI` + `LangGraph`) that runs the assistant.
- Distributed executors: Docker sandboxes for isolation with support for external node runners.
- Built-in tools such as filesystem access, shell, browser, web tools.
- Support for [Agent skills](https://agentskills.io/) (per-user) and MCP servers.
- Scheduled jobs / cronjobs.
- Memory indexing and retrieval (PostgreSQL + pgvector).
- Human-in-the-loop approvals for sensitive tools.
- Encrypted secret storage with human approvals for secret usage (API keys, passwords, ...).
- Multiple client apps over one API: Discord bot (recommended for first-time setup), admin web UI, standalone TUI, a native macOS menubar app, and a native iPhone/iPad app.

Skitter is largely inspired by OpenClaw.

> [!NOTE]  
> A dedicated documentation website is in progress (see `./docs`). For now, please use this `README.md`.

## Applications

| App | Location | Purpose |
| --- | --- | --- |
| Server | `/skitter` | Agent runtime, API, scheduling, heartbeats, tools, memory |
| Admin Web UI | `/admin-web` | Operational dashboard (sessions, tool runs, jobs, memory, sandbox, settings) |
| Standalone TUI | `/skitter-tui` | Remote terminal chat client over API |
| macOS Menubar App | `/skitter-menubar` | Native companion app with quick chat + status |
| Native iOS App | `/skitter-ios` | Universal iPhone/iPad client with chat, inline approvals, voice mode, and notification support |
| Executor Node | `/skitter/node` | External host runner (macOS/Linux) that connects to API via WebSocket |

## Prerequisites

- Docker + Docker Compose
- LLM provider access (API base + key) for `config.yaml`
- macOS 14+ with Xcode 15.4+ / Swift toolchain (menubar and iOS apps)
- Python `3.11+` and Node.js `18+` (only needed for non-Docker/local development)

## Setup (Docker, Recommended)

The easiest install/upgrade path is the root setup script after cloning the repo:

```bash
./setup.sh install
```

It will:

- check required tools (`git`, Docker, Docker Compose, `python3`, `openssl`)
- create `.env` and `config.yaml` if they are missing
- generate secure values for `SKITTER_API_KEY`, `SKITTER_BOOTSTRAP_CODE`, and a valid Fernet `SKITTER_SECRETS_MASTER_KEY`
- build the Docker images and start `postgres`, `api`, and `admin-web`

Note: you must still set some values in `config.yaml` first, for example your LLM providers, API keys, models, and Discord bot token if Discord is enabled.
Edit the file directly or use the admin web UI, then restart with `./setup.sh restart`.

Once the API server is running, open the Admin Web UI, set up a Discord bot, or connect with a different client (TUI, macOS, or iOS app).

If you want to use Discord, see the bot setup guide in `docs/components/discord-transport.md`.

Other useful commands:

```bash
./setup.sh doctor
./setup.sh status
./setup.sh restart
./setup.sh logs api
./setup.sh backup
./setup.sh restore backups/<name>
./setup.sh upgrade latest
./setup.sh uninstall
```

If you want the manual path instead, keep reading below.

## Manual Docker Setup

### 1) Clone the repo and prepare config files

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

### 2) Configure required env vars in `.env`

Generate a valid Fernet key for `SKITTER_SECRETS_MASTER_KEY`:

```bash
python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Generate random values for `SKITTER_API_KEY` and `SKITTER_BOOTSTRAP_CODE` with:

```bash
openssl rand -hex 24
```

Set these values in `.env`:

```bash
SKITTER_CONFIG_PATH=config.yaml
SKITTER_API_KEY=
SKITTER_BOOTSTRAP_CODE=
SKITTER_SECRETS_MASTER_KEY=
ADMIN_WEB_API_BASE_URL=http://localhost:8000
```

### 3) Configure models/providers in `config.yaml`

At minimum, set:

- `providers` (`name`, optional `api_type` = `openai|anthropic`, `api_base`, `api_key`)
- `models` (`name`, `provider`, `model_id`, token costs)
- `main_model` (ordered fallback list of `provider/model`)
- `heartbeat_model` (ordered fallback list of `provider/model`)
- `discord.token` (if Discord transport is enabled)

If you want to use Discord, see the bot setup guide in `docs/components/discord-transport.md`.

Other options (can be edited in the admin web UI):

Web search config:

- `web_search.engine`: `brave` or `searxng`
- `web_search.brave.api_key` / `web_search.brave.api_base`
- `web_search.searxng.api_base` (for local profile use `http://searxng:8080/search`)

MCP config (bring-your-own MCP servers):

- `mcp.servers[]` entries with:
  - `name`
  - `description` for prompt-time discovery and use-case guidance
  - `enabled`
  - `transport`: `stdio` (default) or `http`
  - for `stdio`: `command`, `args`, optional `env`, `cwd`
  - for `http`: `url`, optional `headers`
  - optional for both: `startup_timeout_seconds`, `request_timeout_seconds`

### 4) Build images

```bash
docker compose --profile sandbox build
```

This builds `api`, `admin-web`, and `skitter-sandbox`.

### 5) Start the stack

```bash
docker compose up -d postgres api admin-web
```

Endpoints:

- API: `http://localhost:8000`
- Admin Web UI: `http://localhost:5173`

Notes:

- The `sandbox` image is built but not started as a long-running service. The API spawns per-user sandbox containers on demand via Docker socket access.
- The admin web asks for the admin API key on first use, stores it client-side in the browser, and sends it on subsequent API requests. Treat the UI as a privileged admin surface and avoid using it on shared or untrusted machines.

### 6) Optional profiles

Run SearXNG locally:

```bash
docker compose --profile searxng up -d searxng
```

Then set in `config.yaml`:

```yaml
web_search:
  engine: searxng
  searxng:
    api_base: http://searxng:8080/search
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

> [!CAUTION]
> This runs an executor process **without** a Docker sandbox, directly on the host, with the user's permissions.
> This is an advanced feature. Only use it if you understand the implications.

1. Open Admin Web UI → **Executors**.
2. Click **Add executor node** and create token/command.
3. Clone the repo and run the generated command on the target host (macOS/Linux):

```bash
pip install "."
skitter-node --api-url "http://<api-host>:8000" --token "<token>" --name "<node-name>" --workspace-root "<path>" --write-config
```

After the first run, you can start the executor again by simply running `skitter-node`. The config is stored in `$HOME/.config/skitternode/config.yaml`.

4. Node appears online in Executors view once connected.

5. Ask your agent to list the available executor nodes, or to run a command on the new node.

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
- iOS: use chat commands `/machine` / `/machine <name_or_id>`.

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

On first load, the admin UI will ask for the Skitter admin API key and store it in the browser. You can change it later from the Settings section inside the app.

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

### Native iOS App

Open `skitter-ios/Skitter.xcodeproj` in Xcode, select the `Skitter` scheme, then run on an iPhone, iPad, or simulator.

CLI build:

```bash
xcodebuild -project skitter-ios/Skitter.xcodeproj -scheme Skitter -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

Current app capabilities:

- Bootstrap, pair-code, and access-token sign in
- Active-session chat with markdown rendering
- Inline tool approval cards inside chat
- File and image attachments with in-app preview/download
- Slash commands such as `/new`, `/model`, `/machine`, and `/info`
- Dedicated voice mode, chat dictation, and reply TTS
- iPhone and iPad layouts from the same app target
- Local notification prompts, badge updates, and app-side APNs token capture

Notes:

- The iOS client targets iOS 17+.
- Push notification plumbing exists on the app side; server-driven remote push registration is still a follow-up.
- For simulator or local unsigned builds, use the `xcodebuild` command above. For device install, open the project in Xcode and use your normal signing setup.

## Non-Docker Server Setup (Local/Advanced)

Use this only if you do not want to run the API in Docker.

### 1) Install backend dependencies locally

```bash
python -m venv venv
source venv/bin/activate
pip install -e .[dev]
```

### 2) Start PostgreSQL

Quick option (still using Docker for DB only):

```bash
docker compose up -d postgres
```

Or run your own PostgreSQL+pgvector and point `database.url` in `config.yaml` to it.

### 3) Build sandbox image (if using Docker executor fallback)

```bash
docker build -f skitter/sandbox/Dockerfile -t skitter-sandbox .
```

If you only use external executor nodes and disable Docker auto-fallback, this can be skipped.

### 4) Initialize DB schema and run server

```bash
python -m skitter.data.init_db
python -m skitter.server
```

To run without Discord, set this in `config.yaml`:

```yaml
discord:
  enabled: false
```

## Architecture (High Level)

- `skitter/core`: runtime, graph, sessions, memory, scheduler, heartbeats, sub-agents.
- `skitter/api`: `/v1/*` API routes and auth middleware.
- `skitter/tools`: approvals, executor router, docker sandbox manager.
- `skitter/sandbox`: tool runner app used by docker sandbox and external executor node.
- `skitter/node`: external executor process (`skitter-node`).
- `skitter/data`: models, repositories, schema init.
- `workspace-skeleton`: default per-user workspace bootstrap content.

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

### A) No Discord (menubar/TUI/iOS)

1. Set `SKITTER_BOOTSTRAP_CODE` in the server environment.
2. In the menubar app, TUI, or iOS app, run bootstrap with the setup code and a display name.
3. The client receives a user access token and connects.

### B) Start from Discord

1. DM the bot once (user is created as pending).
2. Admin approves the user in Admin UI (`Users` page).
3. In Discord, run `/pair` to get a short-lived pair code.
4. Use that code in menubar/TUI/iOS pairing flow.

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

MIT (see `LICENSE`).
