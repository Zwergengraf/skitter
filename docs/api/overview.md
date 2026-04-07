# API Overview

Skitter exposes a versioned REST API under `/v1`.

## Auth Model

- admin API key
- user bearer tokens

Admin routes can target any user. User tokens can only target their own resources.

## Main Route Groups

- `/v1/auth`
- `/v1/sessions`
- `/v1/messages`
- `/v1/commands`
- `/v1/profiles`
- `/v1/transport-accounts`
- `/v1/schedules`
- `/v1/agent-jobs`
- `/v1/secrets`
- `/v1/executors`
- `/v1/runs`

## Profile-Aware API Surface

Many routes now accept or return:

- `agent_profile_id`
- `agent_profile_slug`
- `target_transport_account_key`

## Transport-Aware API Surface

Transport account management uses `account_key`, not only DB ids, so the synthetic shared default Discord account can participate in the same UI and API flows as real DB-backed accounts.

## Streaming and Events

The API also exposes:

- session events
- admin events
- run traces and tool runs
