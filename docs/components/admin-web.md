# Admin Web UI

The admin web UI is the main operator surface for Skitter.

## Main Responsibilities

- view sessions, messages, tool runs, and run traces
- approve users
- manage executors
- inspect schedules and jobs
- edit config
- manage profiles and transport accounts

## Profiles Page

The `Profiles` page now handles:

- list profiles for a user
- create, clone, rename, archive, restore, and delete archived profiles
- set the default profile
- inspect and manage Discord transport accounts
- manage public Discord channel bindings

## Discord Management

The admin web UI can show:

- the shared default Discord bot from `config.yaml`
- dedicated per-profile Discord override bots
- discovered servers and channels per bot
- bindings with `mention_only` or `all_messages`

## Why It Matters

Most of the newer multi-agent and multi-bot features are intentionally admin-driven:

- profile creation and lifecycle
- dedicated bot token management
- public channel binding
- transport debugging
