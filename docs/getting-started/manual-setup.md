# Manual Setup

This path gets you to a running local stack (DB + API + optional clients) as an alternative to the Docker setup, useful for quick development/testing.

If you want the simplest install/upgrade workflow instead, use:

```bash
./setup.sh install
```

Useful companions:

```bash
./setup.sh install-cli
./setup.sh install-tui
./setup.sh doctor
./setup.sh status
./setup.sh restart
./setup.sh logs api
./setup.sh backup
./setup.sh restore backups/<name>
./setup.sh upgrade latest
./setup.sh uninstall
```

If you installed `skitter-node` or `skitter-tui` with `./setup.sh install-cli` or `./setup.sh install-tui`, `./setup.sh upgrade ...` refreshes those CLI environments too.

## Prerequisites

- Python 3.11+
- Docker (for PostgreSQL)
- Node 18+ (only if you also run the admin web UI)

## 1) Install

```bash
python -m venv venv
source venv/bin/activate
pip install -e .[dev]
```

## 2) Create Config Files

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

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

## 3) Configure models/providers in `config.yaml`

At minimum, set:

- `providers` (`name`, optional `api_type` = `openai|anthropic`, `api_base`, `api_key`)
- `models` (`name`, `provider`, `model_id`, token costs)
- `main_model` (ordered fallback list of `provider/model`)
- `heartbeat_model` (ordered fallback list of `provider/model`)
- `discord.token` (if Discord transport is enabled)

## 4) Start PostgreSQL and Initialize DB

```bash
docker compose up -d postgres
python -m skitter.data.init_db
```

## 5) Start API Server

```bash
python -m skitter.server
```

Optional (disable Discord transport in `config.yaml`):

```yaml
discord:
  enabled: false
```

## 6) Optional: Start Admin Web UI

```bash
cd admin-web
npm install
npm run dev
```

Admin UI default: `http://localhost:5173`
API default: `http://localhost:8000`

## 7) Bootstrap First User (No Discord Required)

Use the bootstrap code you set in `.env`:

```bash
curl -sS -X POST http://localhost:8000/v1/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{
    "bootstrap_code": "<your-bootstrap-code>",
    "display_name": "User",
    "device_name": "local-dev",
    "device_type": "tui"
  }'
```

The response includes a user access token (`token`).

## 8) Smoke Test a Command

```bash
curl -sS -X POST http://localhost:8000/v1/commands/execute \
  -H "Authorization: Bearer <user-token>" \
  -H 'Content-Type: application/json' \
  -d '{
    "command": "tools",
    "origin": "api"
  }'
```

## 9) Connect a Client

- TUI: [Local Development](local-development.md)
- Menubar app: [Local Development](local-development.md)
- Discord: DM the bot account directly (Discord is DM-only at the moment)
