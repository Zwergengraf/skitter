# Configuration

- `config.yaml` structure and top-level sections.
- Environment-only secrets and overrides.
- Providers/models configuration model.
- Web search provider config:
  - `web_search.engine` (`brave` or `searxng`)
  - `web_search.brave.api_key`, `web_search.brave.api_base`
  - `web_search.searxng.api_base`
- `web_search` tool arguments are `query` and optional `count`.
- Tool/runtime/job/scheduler limits.
- Executor and sandbox-related settings.
- Safe defaults vs production overrides.
