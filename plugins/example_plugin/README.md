# Example Plugin

This plugin is a reference implementation for Skitter's native Python plugin
API. It registers every currently supported non-memory hook and writes a short
debug log line when each hook fires.

It is disabled by default. To try it locally, set `enabled: true` in
`plugin.yaml` and restart the API server.

The plugin does not mutate model messages or tool inputs. The LLM hooks return
`None`, and tool-call hooks are observer-only.

## Registered Hooks

### `server.started`

Fields:

- `started_at`
- `plugin_root`
- `plugin_count`

### `server.stopping`

Fields:

- `started_at`
- `stopping_at`

### `session.started`

Fields:

- `session_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `origin`
- `scope_type`
- `scope_id`

### `run.started`

Fields:

- `run_id`
- `session_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `model`
- `input_text`
- `has_attachments`
- `is_command`
- `started_at`

### `run.finished`

Fields:

- `run_id`
- `session_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `status`
- `model`
- `error`
- `limit_reason`
- `limit_detail`
- `duration_ms`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `cost`
- `response_text`
- `response_preview`
- `finished_at`

### `tool_call.started`

Fields:

- `tool_name`
- `tool_run_id`
- `session_id`
- `run_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `input`
- `status`

### `tool_call.finished`

Fields:

- `tool_name`
- `tool_run_id`
- `session_id`
- `run_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `output`
- `status`
- `executor_id`

### `tool_call.failed`

Fields:

- `tool_name`
- `tool_run_id`
- `session_id`
- `run_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `output`
- `status`
- `executor_id`

### `llm.before_call`

Fields:

- `run_id`
- `session_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `model`
- `attempt`
- `total_attempts`
- `messages`

### `llm.after_call`

Fields:

- `run_id`
- `session_id`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `message_id`
- `origin`
- `transport_account_key`
- `scope_type`
- `scope_id`
- `model`
- `attempt`
- `total_attempts`
- `messages`
- `result`
- `result_messages`
