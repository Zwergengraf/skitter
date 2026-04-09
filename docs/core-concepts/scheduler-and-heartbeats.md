# Scheduler and Heartbeats

Skitter has two main proactive execution models:

- scheduled jobs
- heartbeats

## Scheduled Jobs

Scheduled jobs persist:

- target user
- target profile
- target transport account
- destination channel or DM target
- schedule expression
- prompt
- model selector

That means a job can run as one profile and deliver through the correct Discord bot/account.

## Heartbeats

Heartbeats are profile-scoped.

There is one shared heartbeat scheduler in the API server, but on each tick it:

- lists approved users
- lists each user's profiles
- runs a separate heartbeat flow for each non-archived profile

That means:

- one user with three profiles can have three independent heartbeat runs
- heartbeat history is not shared across profiles
- heartbeat delivery targets are resolved per profile

Heartbeats poll profiles on a cadence and can proactively act if needed.

Heartbeat behavior uses:

- `HEARTBEAT.md` in the profile workspace
- profile metadata such as last private origin, destination, and transport account
- a dedicated heartbeat session for that profile
- that profile's private session for storing the resulting assistant message

The dedicated heartbeat session uses a profile-specific system scope:

```text
system:heartbeat:<profile_id>
```

So heartbeats are isolated from:

- other profiles owned by the same user
- the profile's normal chat history
- other public or private sessions

## `SKITTER_NO_REPLY`

The reserved token for “do nothing / send nothing” is:

```text
SKITTER_NO_REPLY
```

Use it when:

- a heartbeat finds nothing to do
- a group chat does not need a response
- a delivery turn should intentionally stay silent

`HEARTBEAT_OK` is no longer used.

## Delivery Targets

Schedules and heartbeats can deliver back to:

- a private DM surface
- a public bound channel
- the correct transport account for that profile

## Related Pattern

See [Event Inbox + Heartbeats](../patterns/event-inbox-heartbeats.md).
