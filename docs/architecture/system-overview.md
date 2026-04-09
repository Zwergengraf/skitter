# System Overview

Skitter is an API-centric system with profile-aware runtime state and transport-aware delivery.

## Main Layers

- API server
- runtime/tool graph
- transport manager
- scheduler, heartbeat, and job services
- executor routing
- database and memory indexing
- client apps

## Identity Model

- `User` is the human account
- `AgentProfile` is the real agent boundary
- `TransportAccount` is the transport identity

This lets one human own multiple agents, each with different workspaces and transport accounts.

## Transport Model

The transport manager is account-aware.

For Discord, that means:

- one shared default bot from `config.yaml`
- zero or more dedicated per-profile override bots
- explicit public channel bindings

## Execution Model

The runtime is still session-based, but sessions are now:

- profile-aware
- scope-aware
- transport-account-aware for public channels

The server also serializes one active run per session and coalesces backlog in busy public Discord channels.

## Storage Model

Skitter persists:

- sessions and messages
- tool runs and run traces
- schedules and jobs
- secrets
- transport accounts and bindings
- memory entries

Profile workspaces live on disk under `workspace/users/<user>/<profile>/`.
