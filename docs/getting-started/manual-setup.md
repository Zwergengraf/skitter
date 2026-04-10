# Manual Setup

This path gets you to a running local stack without relying on the full Docker install flow.

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
./setup.sh rebuild
./setup.sh restart
./setup.sh logs api
./setup.sh backup
./setup.sh restore backups/<name>
./setup.sh upgrade latest
./setup.sh uninstall
```

Use `./setup.sh rebuild` when you want to apply local code or Dockerfile changes from your current checkout without changing the checked-out git ref.

## Prerequisites

- Python 3.11+
- Docker for PostgreSQL
- Node 18+ if you also run the admin web UI

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

Generate a Fernet key for `SKITTER_SECRETS_MASTER_KEY`:

```bash
python -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Generate random values for `SKITTER_API_KEY` and `SKITTER_BOOTSTRAP_CODE`:

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

## 3) Configure `config.yaml`

At minimum, set:

- `providers`
- `models`
- `main_model`
- `heartbeat_model`
- `workspace.root`
- `discord.enabled`
- `discord.token` if you want the shared default Discord bot

Notes:

- `discord.token` is the shared default Discord bot token.
- Dedicated per-profile Discord bot overrides are configured later in the admin web UI, not in YAML.
- In Docker-first setups, `workspace.root: /workspace` is the normal default.

## 4) Start PostgreSQL and Initialize DB

```bash
docker compose up -d postgres
python -m skitter.data.init_db
```

## 5) Start API Server

```bash
python -m skitter.server
```

If you want no shared Discord bot at all:

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

## 7) Bootstrap First User

Use the bootstrap code from `.env`:

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

The response includes a user access token.

## 8) Smoke Test a Command

```bash
curl -sS -X POST http://localhost:8000/v1/commands/execute \
  -H "Authorization: Bearer <user-token>" \
  -H 'Content-Type: application/json' \
  -d '{
    "command": "profile",
    "origin": "api"
  }'
```

## 9) Connect Clients

- TUI: [Local Development](local-development.md)
- Menubar app: [Local Development](local-development.md)
- Discord:
  - use the shared default bot token from `config.yaml`, or
  - create a dedicated bot override for a profile in the admin web UI

## 10) Enable Public Discord Channels

If you want the agent in normal server channels:

1. Add the bot to the server.
2. Open the admin web UI.
3. Go to `Profiles`.
4. Choose the shared default bot or a dedicated profile bot.
5. Create a channel binding.
6. Choose `mention_only` or `all_messages`.
