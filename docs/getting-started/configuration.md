# Configuration

The Skitter API server uses two config sources:

- `config.yaml` for normal runtime settings
- Environment variables for sensitive/host-specific values

## Load and Override Order

1. Defaults in code (`skitter/core/config.py`)
2. `config.yaml` values
3. Explicit `SKITTER_*` environment variables

This means env vars always win over YAML when both are set.

## Main `config.yaml` Sections

- `database`
- `providers`
- `models`
- `main_model`, `heartbeat_model` (ordered fallback chains)
- `reasoning`
- `embeddings`
- `web_search`
- `browser`
- `discord`
- `heartbeat`
- `workspace`
- `sandbox`
- `executors`
- `limits`, `jobs`, `context`, `tools`, `sub_agents`
- `cors`, `logging`, `prompt`, `users`

Use `config.example.yaml` as the canonical template.

## Providers and Models

Providers define API endpoints and keys. Models reference providers.

```yaml
providers:
  - name: local
    api_type: openai
    api_base: http://localhost:1234/v1
    api_key: ""

models:
  - name: main
    provider: local
    model_id: local-main
    input_cost_per_1m: 0
    output_cost_per_1m: 0

main_model:
  - local/main
heartbeat_model:
  - local/main
```

Model selectors use `provider/model` format. The runtime tries models in order and falls back on provider HTTP failures.

## Web Search Configuration

```yaml
web_search:
  engine: brave # or searxng
  brave:
    api_key: ""
    api_base: https://api.search.brave.com/res/v1/web/search
  searxng:
    api_base: http://localhost:8080/search
```

Notes:

- Tool input is intentionally minimal: `query` and optional `count`.
- For SearXNG, result limiting is done in Skitter after fetching results.

## Runtime Limits

Key guardrails:

- `limits.*` for normal interactive runs
- `jobs.limits.*` for background jobs
- `context.*` for chat/tool message compaction
- `tools.approval_required` and `tools.approval_tools` for approvals

Tune these early in production-like environments to avoid runaway runs.

## Executors and Sandbox

- `executors.auto_docker_default`: auto-create Docker executor fallback
- `sandbox.*`: docker image/network/idle behavior for managed sandbox containers
- `workspace.*`: workspace roots and skeleton location

## Scheduler Timezone

- Scheduler defaults to host timezone unless explicitly set.
- You can override with `scheduler.timezone` in YAML.
- Datetimes are stored in UTC in DB; scheduler interpretation uses configured/default timezone.

## Environment-Only Secrets

Keep these in environment variables (not in YAML):

- `SKITTER_API_KEY`
- `SKITTER_BOOTSTRAP_CODE`
- `SKITTER_SECRETS_MASTER_KEY`

Common optional env flags:

- `SKITTER_CONFIG_PATH`
- `SKITTER_LOG_LEVEL`

## Discord Enablement

Discord transport startup is configured in `config.yaml`, not via env var:

```yaml
discord:
  enabled: true
  token: ""
```
