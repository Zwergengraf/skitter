# Memory

Skitter memory is profile-scoped by default.

## Main Memory Sources

- workspace files such as `MEMORY.md`
- daily and session summary files under `memory/`
- embedded memory entries for semantic retrieval
- prompt context files such as `USER.md`

## Profile Ownership

Each `AgentProfile` has its own workspace and therefore its own:

- `USER.md`
- `MEMORY.md`
- `memory/` files
- indexed memory entries

This keeps multi-profile setups isolated.

## Public Channels

In public Discord channels:

- the agent still runs as the bound profile owner
- the owner profile’s `USER.md` remains part of prompt context
- the actual sender is exposed separately as message context

Skitter does not automatically load a different `USER.md` for every participant in the channel.

## Memory Retrieval

Semantic retrieval stays profile-scoped unless you build a custom cross-profile layer.

That means public-channel messages can reference the same profile memory as private messages for that profile.

## Reindexing

`/memory_reindex` rebuilds memory embeddings from the active profile’s workspace.

## Good Practice

- keep durable preferences in `USER.md` and `MEMORY.md`
- keep chatty session history in sessions, not long-term memory
- use sender context for public-channel participants rather than mixing participant data into the owner workspace
