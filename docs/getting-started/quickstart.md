# Quickstart

This path gets you to a running local stack quickly (DB + API + optional clients).

## Prerequisites

- Python 3.11+
- Docker (for PostgreSQL)
- Node 18+ (only if you also run the admin web UI)

## 1) Clone and Install

```bash
git clone <your-repo-url>
cd Skitter

python -m venv venv
source venv/bin/activate
pip install -e .[dev]
```

## 2) Create Config Files

```bash
cp config.example.yaml config.yaml
cp .env.example .env
```

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set required env vars in `.env`:

```env
SKITTER_CONFIG_PATH=config.yaml
SKITTER_API_KEY=<long-random-admin-key>
SKITTER_BOOTSTRAP_CODE=<one-time-setup-code>
SKITTER_SECRETS_MASTER_KEY=<fernet-key>
```

## 3) Configure Models in `config.yaml`

At minimum, define:

- `providers`
- `models`
- `main_model` (`provider/model`)
- `heartbeat_model` (`provider/model`)

Example shape:

```yaml
providers:
  - name: local
    api_base: http://localhost:1234/v1
    api_key: ""

models:
  - name: main
    provider: local
    model_id: your-main-model
    input_cost_per_1m: 0
    output_cost_per_1m: 0
  - name: heartbeat
    provider: local
    model_id: your-heartbeat-model
    input_cost_per_1m: 0
    output_cost_per_1m: 0

main_model: local/main
heartbeat_model: local/heartbeat
```

## 4) Start PostgreSQL and Initialize DB

```bash
docker compose up -d postgres
python -m skitter.data.init_db
```

## 5) Start API Server

```bash
python -m skitter.server
```

Optional (disable Discord transport):

```bash
SKITTER_ENABLE_DISCORD=false python -m skitter.server
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
    "display_name": "Gabriel",
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
