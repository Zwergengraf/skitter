# Profiles and Transports

This page describes the main identity layers in Skitter.

## Core Concepts

- `User`
  - the human account
- `AgentProfile`
  - one agent identity owned by a user
- `TransportAccount`
  - one transport identity such as a Discord bot
- `TransportSurfaceBinding`
  - a mapping from a public channel/thread to a profile

## Agent Profiles

Each profile has its own:

- workspace
- sessions
- memory
- secrets
- schedules
- jobs
- executor defaults

Each user has:

- one default profile
- one or more additional profiles

Clients can choose different active profiles at the same time.

## Workspace Layout

Profile workspaces live at:

```text
workspace/users/<user_id>/<profile_slug>/
```

New profile workspaces are created from `workspace-skeleton`.

## Discord Transport Accounts

Skitter supports two Discord account types:

- shared default bot
  - configured in `config.yaml`
  - runtime account key: `discord:default`
- dedicated override bot
  - created per profile in the admin web UI
  - stored as a real `transport_accounts` row plus encrypted secret

If a profile has a dedicated Discord bot, the shared default bot cannot act as that profile.

## Surface Bindings

Discord DMs do not need channel bindings.

Public Discord channels do.

Each binding chooses:

- transport account
- target profile
- surface id
- mode

Modes:

- `mention_only`
- `all_messages`

## Delivery

Jobs, schedules, heartbeats, approvals, and prompts can all target a specific transport account.

That keeps outbound messages on the same bot identity that owns the conversation.
