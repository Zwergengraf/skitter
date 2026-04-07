# Configuration

The Skitter API server reads:

- `config.yaml` for normal runtime settings
- environment variables for secrets and host-specific overrides

## Load Order

1. defaults in code
2. `config.yaml`
3. `SKITTER_*` environment variables

## Main `config.yaml` Sections

- `database`
- `providers`
- `models`
- `main_model`, `heartbeat_model`
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

Use `config.example.yaml` as the template.

## Providers and Models

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

Model selectors use `provider/model`.

## Workspace Settings

Important fields:

- `workspace.root`
- `workspace.host_root`
- `workspace.skeleton`

Recommended default for Docker deployments:

```yaml
workspace:
  root: /workspace
```

What `host_root` means:

- `workspace.root` is the path seen by the Skitter API process.
- `workspace.host_root` is the path seen by the Docker host when Skitter needs to create bind mounts for sandbox containers.
- If `host_root` is empty, Skitter falls back to `workspace.root`.

That fallback is fine when the API runs directly on the host, and often also works in Docker if mount detection succeeds.

## Discord Configuration

Discord startup is controlled in `config.yaml`:

```yaml
discord:
  enabled: true
  token: ""
```

Important meaning:

- `discord.enabled` enables the shared default Discord bot.
- `discord.token` is the shared default bot token.
- Extra per-profile Discord bot tokens are not stored here. They are created in the admin web UI and stored in encrypted secrets.

## Executors and Sandbox

- `executors.auto_docker_default`: auto-create Docker executor fallback
- `sandbox.*`: image/network/idle behavior for managed profile-aware sandbox containers

Skitter no longer uses a shared Docker sandbox fallback URL. Docker-backed sandbox execution is managed per profile.

## Environment-Only Secrets

Keep these in environment variables, not in YAML:

- `SKITTER_API_KEY`
- `SKITTER_BOOTSTRAP_CODE`
- `SKITTER_SECRETS_MASTER_KEY`

Common optional env vars:

- `SKITTER_CONFIG_PATH`
- `SKITTER_LOG_LEVEL`

## Scheduler and Timezone

- Scheduler defaults to host timezone unless explicitly set.
- Datetimes are stored in UTC in the database.
- Heartbeats and schedules can deliver through profile-specific transport accounts.
