# Plugins and Hooks

Skitter plugins are trusted Python modules loaded by the API server from the
configured plugin root. Each plugin lives in its own subdirectory with a
`plugin.yaml`, `plugin.yml`, or `plugin.json` manifest.

```yaml
id: example_plugin
enabled: true
required: false
version: 0.1.0
entrypoint: example_plugin:register
capabilities:
  hooks:
    - run.started
    - llm.before_call
config:
  logger_name: skitter.plugins.example_plugin
```

```python
def register(ctx):
    ctx.register_hook("run.started", on_run_started)
    ctx.register_hook("llm.before_call", before_llm_call, priority=50)
```

Hooks receive one event object, usually a dictionary. Most lifecycle hooks are
observer hooks: they can log, enqueue background work, or sync external systems,
but their return value is ignored. Transform hooks can return structured patch
data that Skitter applies to the current LLM or memory operation.

## Return Values

Hook handlers can be sync or async.

```python
def on_run_started(event):
    ...

async def before_llm_call(event):
    ...
```

Supported transform return shapes:

- `None`: no change
- a patch dictionary
- `{"patch": {...}}`
- a dataclass whose fields become the patch
- a Pydantic-style object with `model_dump()`

Only successful hook results are applied. Hook failures are logged and skipped.
When several hooks return patches for the same event, patches are applied in
hook priority order.

Example:

```python
def before_llm_call(event):
    return {
        "append_messages": [
            {
                "role": "system",
                "content": "Prefer concise answers for this run.",
            }
        ]
    }
```

Observer hook return values are ignored. In the current implementation, run and
tool lifecycle hooks cannot change run status, tool input, tool output, tool
approval, token usage, or cost accounting. Tool input transforms are not
supported.

## Hook Aliases

Plugins may use dotted hook names or the original underscore aliases.

| Alias | Canonical hook |
| --- | --- |
| `server_started` | `server.started` |
| `server_stopping` | `server.stopping` |
| `session_started` | `session.started` |
| `run_started` | `run.started` |
| `run_finished` | `run.finished` |
| `tool_call_started` | `tool_call.started` |
| `tool_call_finished` | `tool_call.finished` |
| `tool_call_failed` | `tool_call.failed` |
| `session_memory_updated` | `memory.session_memory.updated` |
| `session_archived` | `memory.session.archived` |
| `before_context_build` | `memory.context.before_build` |
| `after_context_build` | `memory.context.after_build` |
| `before_llm_call` | `llm.before_call` |
| `after_llm_call` | `llm.after_call` |
| `before_memory_recall` | `memory.recall.before` |
| `after_memory_recall` | `memory.recall.after` |
| `before_memory_store` | `memory.store.before` |
| `after_memory_store` | `memory.store.after` |

## Common Context Objects

Memory hooks and memory providers use dataclasses rather than serialized JSON.

### `MemoryContext`

| Field | Type | Meaning |
| --- | --- | --- |
| `user_id` | `str` | Current Skitter user. |
| `agent_profile_id` | `str` | Current profile id. |
| `agent_profile_slug` | `str` | Current profile slug. |
| `session_id` | `str | None` | Current session id, if any. |
| `run_id` | `str | None` | Current run id, if any. |
| `origin` | `str` | Source such as `api`, `discord`, `scheduler`, or `tool`. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Conversation scope type, usually `private` or transport-specific. |
| `scope_id` | `str` | Conversation scope id. |
| `workspace_root` | `Path | None` | Profile workspace root. |

### `ContextContribution`

| Field | Type | Meaning |
| --- | --- | --- |
| `provider_id` | `str` | Provider or hook that produced the context. |
| `title` | `str` | Heading used when rendering context. |
| `content` | `str` | Context text. |
| `priority` | `int` | Lower values are inserted first. |
| `token_estimate` | `int | None` | Optional token estimate for budgeting. |
| `metadata` | `dict` | Provider-specific metadata. |

### `MemoryHit`

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Provider-stable memory id. |
| `provider_id` | `str` | Provider id. |
| `content` | `str` | Memory text. |
| `score` | `float | None` | Relevance score. |
| `kind` | `str | None` | Provider-defined kind, such as `fact` or `preference`. |
| `tags` | `list[str]` | Tags. |
| `source` | `str | None` | Source file, system, or provider reference. |
| `created_at` | `str | None` | Creation timestamp if known. |
| `metadata` | `dict` | Provider-specific metadata. |

### `MemoryItem`

| Field | Type | Meaning |
| --- | --- | --- |
| `content` | `str` | Memory text to store. |
| `kind` | `str` | Memory kind, default `fact`. |
| `importance` | `float | None` | Optional importance score. |
| `confidence` | `float | None` | Optional confidence score. |
| `tags` | `list[str]` | Tags. |
| `source` | `MemorySource` | Source such as `tool`, `archive`, or `session_memory`. |
| `metadata` | `dict` | Provider-specific metadata. |

## Lifecycle Hooks

### `server.started`

Called during API lifespan startup after plugins are loaded, memory providers
are registered, and the memory hub has started.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `started_at` | `str` | API startup timestamp as ISO text. |
| `plugin_root` | `str` | Configured plugin root. |
| `plugin_count` | `int` | Number of discovered plugin manifests. |

Output:

- Observer only. Return value is ignored.

### `server.stopping`

Called during API shutdown before the memory hub shuts down.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `started_at` | `str` | Original API startup timestamp as ISO text. |
| `stopping_at` | `str` | Shutdown timestamp as ISO text. |

Output:

- Observer only. Return value is ignored.

### `session.started`

Called when Skitter creates a new active session for a profile and scope.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | `str` | New session id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str` | Profile id. |
| `agent_profile_slug` | `str` | Profile slug. |
| `origin` | `str` | Message origin or transport. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |

Output:

- Observer only. Return value is ignored.

### `run.started`

Called after a user message has been accepted and the runtime has resolved the
session, profile, scope, and selected model.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | Run id. |
| `session_id` | `str` | Session id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str` | Incoming message id. |
| `origin` | `str` | Message origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `model` | `str` | Selected model name. |
| `input_text` | `str` | Incoming user text. |
| `has_attachments` | `bool` | Whether the message had attachments. |
| `is_command` | `bool` | Whether the message was handled as a command. |
| `started_at` | `str` | Run start timestamp as ISO text. |

Output:

- Observer only. Return value is ignored.
- Use `llm.before_call` if a plugin needs to affect model input for the run.

### `run.finished`

Called after the run is complete and Skitter has computed response text, usage,
cost, and final status.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | Run id. |
| `session_id` | `str` | Session id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str` | Incoming message id. |
| `origin` | `str` | Message origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `status` | `str` | Final run status. |
| `model` | `str` | Final model name. |
| `error` | `str | None` | Error text if the run failed. |
| `limit_reason` | `str | None` | Limit reason, if stopped by limits. |
| `limit_detail` | `str | None` | Limit detail, if any. |
| `duration_ms` | `int` | Runtime duration in milliseconds. |
| `input_tokens` | `int` | Input token count. |
| `output_tokens` | `int` | Output token count. |
| `total_tokens` | `int` | Total token count. |
| `cost` | `float` | Estimated cost. |
| `response_text` | `str` | Final assistant text. |
| `response_preview` | `str` | Short response preview. |
| `finished_at` | `str` | Finish timestamp as ISO text. |

Output:

- Observer only. Return value is ignored.
- Returning a patch here does not change the persisted response or run status.

## Tool Call Hooks

Tool call hooks are lifecycle observers. They cannot rewrite tool arguments,
block execution, replace tool output, or change tool status. Use core tool
approval and policy features for those behaviors.

### `tool_call.started`

Called immediately before a tool function begins its work.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool_name` | `str` | Tool name. |
| `tool_run_id` | `str` | Tool run id. |
| `session_id` | `str` | Session id. |
| `run_id` | `str | None` | Run id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str | None` | Incoming message id. |
| `origin` | `str` | Origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `input` | `dict` | Tool input payload. |
| `status` | `str` | Always `started` for this hook. |

Output:

- Observer only. Return value is ignored.

### `tool_call.finished`

Called after a tool completes successfully or with a non-failed terminal status.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool_name` | `str | None` | Tool name, if known. |
| `tool_run_id` | `str` | Tool run id. |
| `session_id` | `str` | Session id. |
| `run_id` | `str | None` | Run id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str | None` | Incoming message id. |
| `origin` | `str` | Origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `output` | `dict` | Tool output payload. |
| `status` | `str` | Tool status. |
| `executor_id` | `str | None` | Executor id for executor-backed tools. |

Output:

- Observer only. Return value is ignored.

### `tool_call.failed`

Called after a tool fails or is denied.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool_name` | `str | None` | Tool name, if known. |
| `tool_run_id` | `str` | Tool run id. |
| `session_id` | `str` | Session id. |
| `run_id` | `str | None` | Run id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str | None` | Incoming message id. |
| `origin` | `str` | Origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `output` | `dict` | Error or denial output payload. |
| `status` | `str` | Usually `failed` or `denied`. |
| `executor_id` | `str | None` | Executor id for executor-backed tools. |

Output:

- Observer only. Return value is ignored.

## LLM Hooks

LLM hooks are transform hooks. They can change the message list sent to the
graph or the result message list read by the runtime.

Message patches accept LangChain `BaseMessage` instances or dictionaries.

```python
{
    "role": "system" | "developer" | "user" | "assistant" | "tool",
    "content": "...",
    "additional_kwargs": {},
    "tool_call_id": "required for tool messages",
}
```

### `llm.before_call`

Called immediately before the runtime invokes the agent graph for one model
attempt.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | Run id. |
| `session_id` | `str` | Session id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str` | Incoming message id. |
| `origin` | `str` | Message origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `model` | `str` | Candidate model for this attempt. |
| `attempt` | `int` | 1-based attempt number. |
| `total_attempts` | `int` | Number of candidate attempts. |
| `messages` | `list[BaseMessage]` | Messages about to be sent to the graph. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `messages` | `list[BaseMessage | dict]` | Replace the full message list. |
| `prepend_messages` | `list[BaseMessage | dict]` | Insert messages at the beginning. |
| `append_messages` | `list[BaseMessage | dict]` | Append messages at the end. |
| `drop_message_indexes` | `int | list[int]` | Drop zero-based message indexes. |

Example:

```python
def before_llm_call(event):
    return {
        "prepend_messages": [
            {"role": "system", "content": "Use compact answers for this run."}
        ],
        "drop_message_indexes": [],
    }
```

### `llm.after_call`

Called after the graph returns and before the runtime reads the returned message
list. Patching messages here can affect the assistant message that Skitter
persists and returns.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `run_id` | `str` | Run id. |
| `session_id` | `str` | Session id. |
| `user_id` | `str` | Skitter user id. |
| `agent_profile_id` | `str | None` | Profile id. |
| `agent_profile_slug` | `str | None` | Profile slug. |
| `message_id` | `str` | Incoming message id. |
| `origin` | `str` | Message origin or transport. |
| `transport_account_key` | `str | None` | Transport account key, if any. |
| `scope_type` | `str` | Scope type. |
| `scope_id` | `str` | Scope id. |
| `model` | `str` | Candidate model for this attempt. |
| `attempt` | `int` | 1-based attempt number. |
| `total_attempts` | `int` | Number of candidate attempts. |
| `messages` | `list[BaseMessage]` | Messages that were sent to the graph after `llm.before_call` patches. |
| `result` | `dict` | Raw graph result dictionary. |
| `result_messages` | `list[BaseMessage]` | `result["messages"]` when present, otherwise the sent messages. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `messages` | `list[BaseMessage | dict]` | Replace `result["messages"]`. |
| `prepend_messages` | `list[BaseMessage | dict]` | Insert messages at the beginning of `result["messages"]`. |
| `append_messages` | `list[BaseMessage | dict]` | Append messages to `result["messages"]`. |
| `drop_message_indexes` | `int | list[int]` | Drop zero-based indexes from `result["messages"]`. |
| `metadata` | `dict` | Merge into `result["metadata"]`. |

Example:

```python
def after_llm_call(event):
    return {
        "metadata": {"plugin_reviewed": True}
    }
```

## Memory Hook Return Rules

Memory hook events include `ctx` plus a typed request, result, or event object.
The `before` hooks that build, recall, or store memory can patch the request.
The matching `after` hooks can patch the merged result.

Provider lifecycle, forget, turn, and session hooks are observer-only unless
explicitly documented otherwise below.

## Memory Provider Lifecycle Hooks

### `memory.provider.startup`

Called before a provider's `startup()` method.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `provider_id` | `str` | Provider id about to start. |

Output:

- Observer only. Return value is ignored.

Provider method output:

- `MemoryProvider.startup(ctx: MemorySystemContext) -> None`

### `memory.provider.shutdown`

Called before a provider's `shutdown()` method during API shutdown.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `provider_id` | `str` | Provider id about to shut down. |

Output:

- Observer only. Return value is ignored.

Provider method output:

- `MemoryProvider.shutdown(ctx: MemorySystemContext) -> None`

### `memory.health.check`

Called before Skitter checks one provider's health for memory status.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `provider_id` | `str` | Provider id being checked. |

Output:

- Observer only. Return value is ignored.

Provider method output:

- `MemoryProvider.health(ctx: MemoryContext) -> MemoryHealth`
- `MemoryHealth.status`: `ok`, `degraded`, `error`, or `disabled`
- `MemoryHealth.message`: human-readable detail
- `MemoryHealth.metadata`: provider-specific metadata

## Memory Context Hooks

### `memory.context.before_build`

Called before automatic memory context is assembled for a run.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryContextRequest` | Context build request. |

`MemoryContextRequest` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `query` | `str` | Query derived from the incoming turn. |
| `recent_messages` | `list[dict]` | Recent user/assistant messages. |
| `max_tokens` | `int` | Context token budget. |
| `filters` | `dict` | Metadata filters. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `query` | `str` | Replace the query. |
| `filters` | `dict` | Merge filters; values of `None` remove keys. |
| `max_tokens` | `int` | Set a smaller or larger token budget. |
| `disabled_providers` | `str | list[str] | set[str]` | Skip providers for this request. Comma-separated strings are accepted. |

Provider method output:

- `MemoryProvider.build_context(ctx, request) -> MemoryContextResult`
- Each provider returns `contributions: list[ContextContribution]`
- `MemoryHub` merges, sorts, and token-trims provider contributions

Example:

```python
def before_context_build(event):
    return {
        "query": event["request"].query + " project preferences",
        "filters": {"kind": "preference"},
        "disabled_providers": ["slow_provider"],
    }
```

### `memory.context.after_build`

Called after provider context contributions have been merged.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryContextRequest` | Final context request after `before` patches. |
| `result` | `MemoryContextResult` | Merged context result. |

`MemoryContextResult` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `contributions` | `list[ContextContribution]` | Contributions that will be rendered as ephemeral context. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `contributions` | `list[ContextContribution | dict]` | Replace all contributions. |
| `add_contributions` | `list[ContextContribution | dict]` | Append contributions. |
| `drop_provider_ids` | `str | list[str] | set[str]` | Remove contributions from providers. |
| `drop_titles` | `str | list[str] | set[str]` | Remove contributions by title. |
| `drop_contributions` | `list[dict | str]` | Add provider/title selectors to the drop sets. String form is `provider_id:title`. |
| `redactions` | `list[dict]` | Replace contribution content. Each item supports `provider_id`, `title`, and `content`. |
| `max_tokens` | `int` | Trim final contributions to this budget. |

Dictionary contributions support `provider_id`, `title`, `content`,
`priority`, `token_estimate`, and `metadata`.

Example:

```python
def after_context_build(event):
    return {
        "redactions": [
            {
                "provider_id": "external",
                "title": "Private Note",
                "content": "[redacted]",
            }
        ],
        "add_contributions": [
            {
                "provider_id": "policy",
                "title": "Local Policy",
                "content": "Do not mention internal ticket IDs.",
                "priority": 10,
            }
        ],
    }
```

## Memory Recall Hooks

### `memory.recall.before`

Called before explicit memory recall/search runs.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryRecallRequest` | Recall request. |

`MemoryRecallRequest` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `query` | `str` | Search query. |
| `top_k` | `int` | Max hits. |
| `source` | `MemorySource` | Source such as `tool`, `command`, `api`, or `context`. |
| `max_tokens` | `int | None` | Optional token budget. |
| `filters` | `dict` | Metadata filters. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `query` | `str` | Replace the query. |
| `filters` | `dict` | Merge filters; values of `None` remove keys. |
| `top_k` | `int` | Change result limit. |
| `max_tokens` | `int` | Change token budget. |
| `disabled_providers` | `str | list[str] | set[str]` | Skip providers for this recall. |

Provider method output:

- `MemoryProvider.recall(ctx, request) -> MemoryRecallResult`
- Each provider returns `hits: list[MemoryHit]` and `errors: dict[str, str]`
- `MemoryHub` dedupes, sorts, and trims hits

### `memory.recall.after`

Called after recall hits are merged.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryRecallRequest` | Final recall request after `before` patches. |
| `result` | `MemoryRecallResult` | Merged recall result. |

`MemoryRecallResult` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `hits` | `list[MemoryHit]` | Merged hits. |
| `errors` | `dict[str, str]` | Provider errors. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `hits` | `list[MemoryHit | dict]` | Replace all hits. |
| `add_hits` | `list[MemoryHit | dict]` | Append hits. |
| `drop_hit_ids` | `str | list[str] | set[str]` | Remove hits by id. |
| `drop_ids` | `str | list[str] | set[str]` | Alias for `drop_hit_ids`. |
| `drop_provider_ids` | `str | list[str] | set[str]` | Remove hits from providers. |
| `redactions` | `list[dict]` | Replace hit content. Each item supports `id`, `provider_id`, and `content`. |
| `errors` | `dict[str, str]` | Merge additional errors. |
| `top_k` | `int` | Trim final hits. |

Dictionary hits support `id`, `provider_id`, `content`, `summary`, `score`,
`kind`, `tags`, `source`, `created_at`, and `metadata`.

Example:

```python
def after_memory_recall(event):
    return {
        "drop_provider_ids": ["experimental"],
        "add_hits": [
            {
                "id": "policy:1",
                "provider_id": "policy",
                "content": "Project memory is profile-scoped.",
                "score": 1.0,
            }
        ],
    }
```

## Memory Store Hooks

### `memory.store.before`

Called before durable memory writes are sent to providers.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryStoreRequest` | Store request. |

`MemoryStoreRequest` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `items` | `list[MemoryItem]` | Items to store. |
| `source` | `MemorySource` | Source such as `tool`, `archive`, `session_memory`, or `api`. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `reject` | `bool | str` | Reject the store. A string is used as the rejection reason. |
| `reason` | `str` | Rejection reason when `reject` is `true`. |
| `source` | `MemorySource` | Replace request source. |
| `items` | `list[MemoryItem | dict]` | Replace all items. |
| `add_items` | `list[MemoryItem | dict]` | Append items. |
| `drop_indexes` | `list[int]` | Remove items by zero-based index. |
| `drop_tags` | `str | list[str] | set[str]` | Remove items containing any listed tag. |
| `disabled_providers` | `str | list[str] | set[str]` | Skip providers for this store. |

Dictionary items support `content`, `kind`, `importance`, `confidence`,
`tags`, `source`, and `metadata`.

Provider method output:

- `MemoryProvider.store(ctx, request) -> MemoryStoreResult`
- Providers return `stored`, `errors`, and `metadata`

Example:

```python
def before_memory_store(event):
    for item in event["request"].items:
        if "api key" in item.content.lower():
            return {"reject": True, "reason": "possible secret"}
    return None
```

### `memory.store.after`

Called after provider store results are merged. If `memory.store.before`
rejected the operation, this hook still fires with a result containing a `hook`
error.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryStoreRequest` | Final store request after `before` patches. |
| `result` | `MemoryStoreResult` | Merged store result. |

`MemoryStoreResult` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `stored` | `int` | Total stored count. |
| `errors` | `dict[str, str]` | Provider errors. |
| `metadata` | `dict` | Provider metadata. |

Output patch:

| Field | Type | Effect |
| --- | --- | --- |
| `stored` | `int` | Replace stored count. |
| `stored_delta` | `int` | Increment or decrement stored count. |
| `errors` | `dict[str, str]` | Merge additional errors. |
| `metadata` | `dict` | Merge metadata. |

## Memory Forget Hooks

### `memory.forget.before`

Called before forget/delete operations are routed to providers.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryForgetRequest` | Forget request. |

`MemoryForgetRequest` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `selector` | `MemoryForgetSelector` | Delete selector. |
| `include_builtin` | `bool` | Whether built-in memory should also be deleted. |

`MemoryForgetSelector` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `user_id` | `str` | User id. |
| `agent_profile_id` | `str` | Profile id. |
| `provider_id` | `str | None` | Optional provider target. |
| `memory_ids` | `list[str] | None` | Optional memory ids. |
| `tags` | `list[str] | None` | Optional tags. |
| `source` | `str | None` | Optional source. |
| `all_for_profile` | `bool` | Delete everything for the profile. |

Output:

- Observer only in the current implementation. Return value is ignored.
- Provider deletion behavior is controlled by `MemoryForgetRequest`.

Provider method output:

- `MemoryProvider.forget(ctx, request) -> MemoryForgetResult`
- Providers return `deleted`, `unsupported`, and `errors`

### `memory.forget.after`

Called after forget results are merged.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `request` | `MemoryForgetRequest` | Forget request. |
| `result` | `MemoryForgetResult` | Merged forget result. |

`MemoryForgetResult` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `deleted` | `int` | Total deleted count. |
| `unsupported` | `bool` | Whether any provider reported unsupported. |
| `errors` | `dict[str, str]` | Provider errors. |

Output:

- Observer only. Return value is ignored.

## Memory Turn And Session Hooks

### `memory.turn.observed`

Called after queued provider `observe_turn()` callbacks finish for a turn.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session/run context. |
| `turn` | `ConversationTurn` | Observed conversation turn. |
| `errors` | `dict[str, str]` | Provider errors from observation. |

`ConversationTurn` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `user_message_id` | `str | None` | User message id. |
| `assistant_message_id` | `str | None` | Assistant message id. |
| `user_text` | `str` | User text. |
| `assistant_text` | `str` | Assistant text. |
| `attachments` | `list[dict]` | Attachment metadata. |
| `created_at` | `datetime` | Turn timestamp. |
| `metadata` | `dict` | Additional metadata. |

Output:

- Observer only. Return value is ignored.

Provider callback:

- `MemoryProvider.observe_turn(ctx, turn) -> None`

### `memory.session_memory.updated`

Called after session sidecar memory is refreshed and provider-specific
`on_session_memory_updated()` callbacks have run.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session context. |
| `event` | `SessionMemoryUpdated` | Session memory update event. |

`SessionMemoryUpdated` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | `str` | Session id. |
| `path` | `str` | Sidecar memory file path. |
| `content` | `str` | Sidecar memory content. |

Output:

- Observer only. Return value is ignored.

Provider callback:

- `MemoryProvider.on_session_memory_updated(ctx, event) -> None`

### `memory.session.archiving`

Called before Skitter creates or updates long-term archive memory for a
session.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session context. |
| `session_id` | `str` | Session id being archived. |

Output:

- Observer only. Return value is ignored.
- Archive prompt rewriting is not supported by this hook.

### `memory.session.archived`

Called after archive handling completes and provider-specific
`on_session_archived()` callbacks have run.

Input:

| Field | Type | Meaning |
| --- | --- | --- |
| `ctx` | `MemoryContext` | Profile/session context. |
| `event` | `SessionArchived` | Archive event. |

`SessionArchived` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | `str` | Session id. |
| `archive_summary` | `str` | New archive summary. |
| `session_memory_path` | `str | None` | Sidecar memory path, if available. |
| `previous_archive_summary` | `str | None` | Previous archive summary, if any. |

Output:

- Observer only. Return value is ignored.

Provider callback:

- `MemoryProvider.on_session_archived(ctx, event) -> None`

## What Hooks Can Change Today

| Area | Hook | Can change state? |
| --- | --- | --- |
| Server lifecycle | `server.*` | No. Observer only. |
| Sessions | `session.started` | No. Observer only. |
| Runs | `run.*` | No. Observer only. |
| Tool calls | `tool_call.*` | No. Observer only. Tool input/output transforms are not supported. |
| LLM input | `llm.before_call` | Yes. Can patch the message list sent to the graph. |
| LLM result | `llm.after_call` | Yes. Can patch `result["messages"]` and result metadata. |
| Memory context request | `memory.context.before_build` | Yes. Can patch query, filters, budget, and disabled providers. |
| Memory context result | `memory.context.after_build` | Yes. Can patch context contributions. |
| Memory recall request | `memory.recall.before` | Yes. Can patch query, filters, budget, count, and disabled providers. |
| Memory recall result | `memory.recall.after` | Yes. Can patch memory hits and errors. |
| Memory store request | `memory.store.before` | Yes. Can normalize, add, drop, or reject items. |
| Memory store result | `memory.store.after` | Yes. Can patch stored count, errors, and metadata. |
| Memory forget | `memory.forget.*` | No hook patching yet. Provider methods perform deletion. |
| Memory turn/session events | `memory.turn.*`, `memory.session.*` | No. Observer/provider callback only. |
