# Docker Compose

Use Docker Compose when you want a containerized core stack.

For most installs, the easiest entrypoint is:

```bash
./setup.sh install
```

That command checks prerequisites, creates missing local config, generates secrets, builds images, and starts the core services.

Useful follow-ups:

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

Backups are stored in `./backups/<timestamp>/` and include `.env`, `config.yaml`, and a PostgreSQL SQL dump.

## Services in `docker-compose.yml`

- `postgres`: PostgreSQL + pgvector
- `api`: Skitter API server
- `admin-web`: admin UI (served by nginx)
- `searxng` (profile `searxng`): optional local web search engine
- `sandbox` (profile `sandbox`): image build target used by API-managed Docker executors

## Required Environment

Set these in your shell or `.env` before running compose:

- `SKITTER_API_KEY`
- `SKITTER_BOOTSTRAP_CODE`
- `SKITTER_SECRETS_MASTER_KEY`

Optional but common:

- `SKITTER_POSTGRES_USER` (default `postgres`)
- `SKITTER_POSTGRES_PASSWORD` (default `postgres`)
- `SKITTER_POSTGRES_DB` (default `skitter`)
- `ADMIN_WEB_API_BASE_URL` (default `http://localhost:8000`)

Discord transport enablement now lives in `config.yaml`:

```yaml
discord:
  enabled: true
```

## Build Images

Build all required images (including sandbox):

```bash
docker compose --profile sandbox build
```

## Start Core Services

```bash
docker compose up -d postgres api admin-web
```

Endpoints:

- API: `http://localhost:8000`
- Admin UI: `http://localhost:5173`

## Optional: Run Local SearXNG

SearXNG is included in the root compose file behind a profile:

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

## Volume and Mount Behavior

- `./workspace` is mounted into API as `/workspace`.
- `./workspace-skeleton` is mounted read-only for workspace bootstrap.
- `./config.yaml` and `./system_prompt.md` are mounted into API.
- Docker socket is mounted so API can create/manage per-user sandbox containers.

## Useful Commands

- Follow API logs:

```bash
docker compose logs -f api
```

- Rebuild only API:

```bash
docker compose build api
docker compose up -d api
```

- Stop everything:

```bash
docker compose down
```

- Reset DB data (destructive):

```bash
docker compose down -v
```
