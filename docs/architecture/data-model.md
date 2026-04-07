# Data Model

## Core Entities

- `users`
- `agent_profiles`
- `sessions`
- `messages`
- `memory_entries`
- `secrets`
- `scheduled_jobs`
- `agent_jobs`

## Profile Layer

The most important new boundary is `AgentProfile`.

Profiles are owned by users, and profile-owned records include:

- sessions
- memory entries
- secrets
- scheduled jobs
- agent jobs
- usage and run traces

## Transport Layer

Transport-related entities now include:

- `transport_accounts`
  - dedicated per-profile override accounts
- synthetic shared transport accounts
  - for example `discord:default`
- `transport_surface_bindings`
  - public channel to profile mappings
- `surface_profile_overrides`
  - private surface overrides such as shared-default Discord DMs

## Session Ownership

Sessions store:

- `user_id`
- `agent_profile_id`
- `scope_type`
- `scope_id`

For public Discord channels, the session still belongs to the bound profile owner, while sender identity is carried in message metadata.

## Delivery State

Schedules and jobs also store:

- `target_origin`
- `target_destination_id`
- `target_transport_account_key`

This keeps outbound delivery on the correct bot/account.
