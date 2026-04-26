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
- show or change the profile default model

### Syntax

Supported forms:

```text
/profile
/profile list
/profile show
/profile help

/profile use <slug>
/profile default <slug>

/profile create <name>
/profile create <name> --default

/profile clone <source_slug> <new_name>
/profile clone <source_slug> <new_name> --mode=blank
/profile clone <source_slug> <new_name> --mode=settings
/profile clone <source_slug> <new_name> --mode=all
/profile clone <source_slug> <new_name> --default

/profile rename <slug> <new_name>

/profile archive <slug>
/profile unarchive <slug>

/profile model
/profile model <model_name>
/profile model default
```

Notes:

- names with spaces should be quoted
- `/profile`, `/profile list`, and `/profile show` currently behave the same
- `/profile help` prints the syntax and examples
- `/profile model default` resets the profile to the global default model
- `/profile delete` is not part of the chat command family; deleting archived profiles is done in the admin web UI

### Examples

```text
/profile
/profile help
/profile use coder
/profile default assistant
/profile create "Research Bot"
/profile create "Ops Bot" --default
/profile clone default "Writer Bot"
/profile clone default "Fresh Copy" --mode=blank
/profile clone assistant "Assistant Fork" --mode=all --default
/profile rename writer "Longform Writer"
/profile archive test-bot
/profile unarchive test-bot
/profile model
/profile model local/gpt-5.4
/profile model default
```

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

## Stop Command

Use `/stop` to stop the active turn for the current session or channel scope.

Behavior:

- cancels the currently running LLM/tool turn
- drops queued/coalesced backlog for that session
- keeps the user's triggering message in history
- adds a hard-coded assistant message: `This turn was stopped by the user.`
- marks the run trace as `cancelled`
- cancels a pending `ask_user` prompt if one is waiting

Examples:

```text
/stop
```

API clients can also call:

```text
POST /v1/sessions/{session_id}/stop
```
