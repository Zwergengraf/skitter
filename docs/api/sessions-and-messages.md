# Sessions and Messages API

## Sessions

Main routes:

- `GET /v1/sessions`
- `POST /v1/sessions`
- `GET /v1/sessions/{session_id}`
- `GET /v1/sessions/{session_id}/detail`
- `POST /v1/sessions/{session_id}/model`

## Session Creation

`POST /v1/sessions` accepts:

- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `origin`
- `reuse_active`
- `scope_type`
- `scope_id`

If no explicit profile is given, the server resolves the user’s default profile.

## Session Ownership

Sessions are profile-aware:

- private sessions are profile-scoped
- public Discord channel sessions are group-scoped
- group scope ids include transport account identity

## Messages

Main route:

- `POST /v1/messages`

The normal API message route is still primarily a private/session API surface, but persisted message metadata now commonly includes:

- `internal_user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `scope_type`
- `scope_id`
- `transport_account_key`

For public Discord messages, persisted metadata can also include sender details.

## Public Discord Messages

In public Discord channels:

- the run executes as the bound profile owner
- sender identity is stored separately in metadata
- busy sessions are serialized and backlog is coalesced on the transport/server side

That queueing behavior is not exposed as a separate API endpoint. It is part of the live transport execution flow.
