# Execution Flow

## 1. Inbound Message Normalization

Each transport maps inbound events into a `MessageEnvelope`.

For Discord, metadata can include:

- `transport_account_key`
- `guild_id`
- `parent_channel_id`
- sender display name, username, mention, bot flag, and roles

## 2. Sender Approval

Before a turn runs, Skitter resolves the sender as an internal user and checks approval.

Behavior differs by surface:

- DM: unapproved sender gets a notice
- public channel: unapproved sender is ignored

## 3. Profile Resolution

Skitter resolves the target profile based on surface type:

- local clients: explicit profile id or user default
- shared default Discord DM: surface override or default profile
- dedicated Discord bot: pinned profile
- public Discord channel: admin surface binding

## 4. Scope and Session Resolution

Skitter resolves a conversation scope and then finds or creates the active session for:

- profile
- scope type
- scope id

Public Discord channels use account-aware group scope ids.

## 5. Session Run Queue

Before the runtime executes, Skitter serializes one active run per session.

If new plain public-channel messages arrive while a run is active:

- they are queued
- backlog is coalesced by default
- the next run sees one combined follow-up batch

## 6. Runtime Invocation

The runtime:

- loads prompt context from the profile workspace
- injects sender context for public Discord messages
- runs the tool/model loop
- extracts attachments and output directives

## 7. Delivery

Outbound replies, approvals, prompts, schedules, jobs, and heartbeats use:

- target origin
- target destination
- target transport account key

That keeps replies on the correct Discord bot identity.

## 8. Persistence and Observability

Skitter persists:

- messages
- tool runs
- run traces
- usage
- pending user prompts

The admin event bus and run traces expose the full flow for debugging.
