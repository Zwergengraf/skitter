# Local Development

This page is the practical day-to-day workflow for developing Skitter locally.

## Requirements

- Python 3.11+
- Docker (Postgres and optional sandbox image build)
- Node.js 18+ (admin web UI)
- Xcode + Swift toolchain (menubar app only)

## Recommended Run Order

1. Start PostgreSQL:

```bash
docker compose up -d postgres
```

2. Initialize schema (safe to re-run):

```bash
python -m skitter.data.init_db
```

3. Start API server:

```bash
python -m skitter.server
```

4. Start optional clients:

- Admin web UI:

```bash
cd admin-web
npm install
npm run dev
```

- TUI:

```bash
cd skitter-tui
python -m venv .venv
source .venv/bin/activate
pip install -e .
skitter-tui --api-url http://localhost:8000
```

- Menubar:

```bash
cd skitter-menubar
swift build
swift run
```

## Useful Environment Variables

- `SKITTER_CONFIG_PATH`: config file path (default `config.yaml`)
- `SKITTER_API_KEY`: admin API key
- `SKITTER_BOOTSTRAP_CODE`: one-time bootstrap code for first user/device
- `SKITTER_SECRETS_MASTER_KEY`: encryption key for per-user secrets
- `SKITTER_LOG_LEVEL`: `DEBUG|INFO|WARNING|ERROR`

Discord transport startup is controlled in `config.yaml`:

```yaml
discord:
  enabled: true
```

## Discord Notes (Current Behavior)

- Discord transport is DM-only.
- Messages from server channels/threads/group chats are ignored.
- Slash commands should be used in DM with the bot.

## Typical Dev Loop

1. Change server/client code.
2. Restart affected process.
3. Run focused tests:

```bash
pytest -q
```

Or narrower:

```bash
pytest skitter/tests/unit -q
pytest skitter/tests/e2e -q
```

## Common Local Checks

- API health:

```bash
curl -sS http://localhost:8000/health
```

- Confirm auth:

```bash
curl -sS http://localhost:8000/v1/auth/me \
  -H "Authorization: Bearer <user-token>"
```

- Verify DB connectivity errors early by watching API logs during startup.
