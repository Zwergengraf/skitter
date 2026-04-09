# Commands API

Commands are executed through:

```text
POST /v1/commands/execute
```

## Request Shape

Important fields:

- `command`
- `args`
- `origin`
- `user_id`
- `agent_profile_id`
- `agent_profile_slug`
- `transport_account_key`

## Profile Commands

All clients support the `/profile` command family:

- show current state
- list profiles
- use profile
- set default profile
- create
- clone
- rename
- archive
- unarchive

## Discord-Specific Rules

On Discord, `/profile use` depends on the surface:

- shared default bot in DM
  - can switch to another profile that does not have a dedicated Discord bot
- dedicated bot
  - rejected because the bot is pinned to its profile
- admin-bound public channel
  - rejected because the channel profile is fixed by binding

## Transport Parity

The goal is that the same command family works across clients, but transports may impose stricter routing rules than local paired clients.
