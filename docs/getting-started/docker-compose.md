# Docker Compose

Use Docker Compose when you want a containerized core stack.

For most installs, the easiest entrypoint is:

```bash
./setup.sh install
```

Useful follow-ups:

```bash
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

Use `./setup.sh rebuild` when you want to rebuild the stack from local source changes, such as a custom sandbox Dockerfile, without changing the checked-out git ref.

## Services in `docker-compose.yml`

- `postgres`
- `api`
- `admin-web`
- `searxng` (optional)
- `sandbox` image build target

## Required Environment

- `SKITTER_API_KEY`
- `SKITTER_BOOTSTRAP_CODE`
- `SKITTER_SECRETS_MASTER_KEY`

Common optional values:

- `SKITTER_POSTGRES_USER`
- `SKITTER_POSTGRES_PASSWORD`
- `SKITTER_POSTGRES_DB`
- `ADMIN_WEB_API_BASE_URL`

## Discord in Docker

The shared default Discord bot is still configured in `config.yaml`:

```yaml
discord:
  enabled: true
  token: ""
```

Dedicated per-profile Discord bot overrides are configured after startup in the admin web UI.

## Build Images

```bash
docker compose --profile sandbox build
```

The Python-based images install dependencies with `uv` into an internal virtualenv during the Docker build. No extra `pip` setup is required on the host.

## Start Core Services

```bash
docker compose up -d postgres api admin-web
```

Endpoints:

- API: `http://localhost:8000`
- Admin UI: `http://localhost:5173`

## Volume and Mount Behavior

- `./workspace` is mounted into the API container as `/workspace`
- `./workspace-skeleton` is mounted read-only
- `./config.yaml` and `./system_prompt.md` are mounted into the API container
- Docker socket is mounted so the API can manage profile-aware sandbox containers

In Docker setups, `workspace.root: /workspace` is the normal configuration.

## Optional: Run Local SearXNG

```bash
docker compose --profile searxng up -d searxng
```

Then configure:

```yaml
web_search:
  engine: searxng
  searxng:
    api_base: http://searxng:8080/search
```

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

- Reset DB data:

```bash
docker compose down -v
```
