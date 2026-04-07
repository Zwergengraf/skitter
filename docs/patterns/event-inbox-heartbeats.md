# Event Inbox + Heartbeat Pattern

Use this pattern when external systems should push updates to Skitter, and heartbeats should only react to new items.

## Goal

- Avoid expensive polling logic inside Skitter heartbeats.
- Keep integrations simple and tool-agnostic.
- Let Skitter focus on reasoning/actions instead of data collection.

## How It Works

1. External automation (for example n8n) writes event files into the user workspace.
2. Heartbeat reads new event files and decides what to do.
3. After handling, files are marked as processed (move folder or state file).

## Suggested Workspace Layout

- `inbox/events/` for new events.
- `inbox/processed/` for completed events.
- `inbox/failed/` for events that need manual retry/review.

## Event File Format

Use one file per event to avoid race conditions and overwrites.

```md
---
event_id: "evt_2026_02_18_001"
source: "n8n"
type: "email_urgent"
created_at: "2026-02-18T19:40:00Z"
priority: "high"
---
Subject: Build pipeline failed
Summary: Main branch deploy failed in step 4.
Action hint: Check latest CI logs and report root cause.
```

## Example HEARTBEAT.md

Put this file in the user workspace as `HEARTBEAT.md`:

```md
# Event Inbox Processor

You are running in heartbeat mode.

1. Read up to 10 oldest files from `/inbox/events`.
2. If `/inbox/events` is missing or empty, reply exactly `SKITTER_NO_REPLY`.
3. For each event file, parse frontmatter (`event_id`, `source`, `type`, `created_at`, `priority`).
4. Perform needed actions using tools only when required.
5. After successful handling, move the file to `/inbox/processed/<same-filename>`.
6. If handling fails, move the file to `/inbox/failed/<same-filename>` and append a one-line failure reason.
7. Skip duplicate events by `event_id` if already handled.
8. Respect quiet hours unless event priority is `high` or `urgent`.
9. If there are no pending actions after processing, reply exactly `SKITTER_NO_REPLY`.

Never invent events. Only act on files that actually exist in `/inbox/events`.
```

## Why This Works Well

- Push model scales better than polling 5+ services every heartbeat.
- Any integration tool can participate by writing files.
- Event history is inspectable directly from workspace files.
- Easy to disable or pause by stopping upstream writes.

## Recommended Guardrails

- Process oldest-first with a fixed max events per heartbeat.
- Deduplicate by `event_id`.
- Respect quiet hours unless `priority` is urgent.
- Keep event files small and explicit (facts + action hint).

## n8n Example Flow

1. Trigger: new email/calendar/task update.
2. Transform payload to markdown event file.
3. Write file to `<user-workspace>/inbox/events/<timestamp>-<event_id>.md`.
4. Let heartbeat consume and react.
