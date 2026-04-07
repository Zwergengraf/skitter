# Sessions

Skitter organizes conversations into sessions scoped to an agent profile.

## Session Model

- Every session belongs to one `User`.
- Every session belongs to one `AgentProfile`.
- A session also has a `scope_type` and `scope_id`.

Common scopes:

- `private`
  - one active private session per profile
- `group`
  - used for public Discord channels and threads
  - keyed by origin + transport account + external channel

## Profile Awareness

Private sessions are profile-scoped, not just user-scoped.

That means:

- one user can have multiple private sessions at the same time
- one client can use profile `default`
- another client can use profile `coder`

## Cross-Transport Behavior

- Menubar, TUI, and API clients usually work with private profile sessions.
- Discord DMs use private profile sessions.
- Public Discord channels use group sessions bound by admin.

## Sender Identity in Public Channels

In public Discord channels, the runtime still executes as the bound profile owner.

The actual sender is carried separately in message metadata and rendered into the model-visible prompt as:

- display name
- username
- mention token
- bot flag
- role names

This lets the agent know who said what without switching ownership of the workspace or memory.

## Queueing and Coalescing

Skitter now serializes one active run per session.

If several plain public-channel messages arrive while the session is already busy:

- new messages are queued
- backlog is coalesced by default
- the next turn receives one combined follow-up batch

Commands, explicit interactions, private chats, and attachment-bearing messages are not coalesced.

## `/new`

`/new` ends the active session for the current scope and starts a new one.

For private scopes, that means:

- the current profile’s private session is archived
- the next run starts with a fresh session

## Context Compaction

Session history can be compacted and summarized over time.

- active transcript remains session-specific
- context summary checkpoints are stored on the session
- long-term memory remains profile-scoped
