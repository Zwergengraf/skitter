# Local Development

This page is the practical day-to-day workflow for developing Skitter locally.

## Requirements

- Python 3.11+
- Docker
- Node.js 18+ for admin web UI
- Xcode + Swift toolchain for the menubar app

## Recommended Run Order

1. Start PostgreSQL:

```bash
docker compose up -d postgres
```

2. Initialize schema:

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
./setup.sh install-tui
skitter-tui --api-url http://localhost:8000
```

- Menubar:

```bash
cd skitter-menubar
swift build
swift run
```

## Useful Environment Variables

- `SKITTER_CONFIG_PATH`
- `SKITTER_API_KEY`
- `SKITTER_BOOTSTRAP_CODE`
- `SKITTER_SECRETS_MASTER_KEY`
- `SKITTER_LOG_LEVEL`

## Discord Notes

The shared default Discord bot is controlled in `config.yaml`:

```yaml
discord:
  enabled: true
  token: ""
```

Current Discord behavior:

- DMs are supported.
- Public server channels and threads are supported through explicit admin bindings.
- Dedicated per-profile Discord bots can override the shared default bot.
- Busy public-channel sessions are serialized and backlog is coalesced by default.

## Typical Dev Loop

1. Change server or client code.
2. Restart the affected process.
3. Run focused tests:

```bash
pytest -q
```

Or narrower:

```bash
pytest skitter/tests/unit -q
pytest skitter/tests/e2e -q
```

## Good Local Smoke Tests

- API health:

```bash
curl -sS http://localhost:8000/health
```

- Auth:

```bash
curl -sS http://localhost:8000/v1/auth/me \
  -H "Authorization: Bearer <user-token>"
```

- Profiles:

```bash
curl -sS http://localhost:8000/v1/profiles \
  -H "Authorization: Bearer <user-token>"
```

- Discord account/binding state:
  - use the admin web UI `Profiles` page
