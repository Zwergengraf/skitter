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

Heartbeats poll profiles on a cadence and can proactively act if needed.

Heartbeat behavior uses:

- `HEARTBEAT.md` in the profile workspace
- profile metadata such as last private origin, destination, and transport account

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
