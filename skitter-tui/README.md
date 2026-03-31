# Skitter TUI (Standalone)

A standalone terminal UI client for interacting with a remote Skitter server over HTTP/SSE.

## Features

- Separate project outside the main `skitter/` server code.
- Token-authenticated API client (`Bearer`).
- Creates/resumes sessions and sends messages through the API.
- Subscribes to `/v1/events/stream` for live status updates.
- Resumes the latest active `tui` session on startup.
- Loads and renders persisted session message history on startup/attach.
- `/new` creates a fresh `tui` session.
- Uses Textual's built-in theming/command palette.
- Assistant attachments (files/images) shown in chat with download links.
- `/download <index> [target_path]` saves the last assistant attachment locally.
- Interactive commands:
  - `/new` start a new session (same behavior as Discord `/new`)
  - `/memory_reindex` rebuild memory embeddings
  - `/memory_search <query>` semantic memory search
  - `/schedule_list` list scheduled jobs
  - `/schedule_delete <job_id>` delete a scheduled job
  - `/schedule_pause <job_id>` pause a scheduled job
  - `/schedule_resume <job_id>` resume a scheduled job
  - `/tools` show tool approval settings
  - `/model [provider/model]` list/set active model
  - `/pair` create pair code (authenticated)
  - `/info` show session usage info
  - `/session` show active session
  - `/whoami` show authenticated user
  - `/bootstrap <setup_code> <display_name>` first-time setup
  - `/pair <pair_code>` pair this TUI to existing account when unauthenticated
  - `/token <access_token>` set token manually
  - `/logout` clear token
  - `/attachments` list attachments from the last assistant reply
  - `/download <index> [target_path]` download one attachment
  - `/clear` clear local chat view
  - `/help` show help
  - `/quit` exit

## Requirements

- Python `>=3.11`
- Reachable Skitter API server

## Install

```bash
# from the repo root
./setup.sh install-tui
```

## Run

```bash
skitter-tui --api-url http://localhost:8000 --access-token <ACCESS_TOKEN>
```

Or with env vars (`SKITTER_API_KEY` is treated as access token):

```bash
export SKITTER_API_URL=http://localhost:8000
export SKITTER_API_KEY=<ACCESS_TOKEN>
skitter-tui
```

Optional attach to an existing session:

```bash
skitter-tui --api-url http://localhost:8000 --session-id <SESSION_ID>
```

## Notes

- This app is API-only and does not access local workspaces.
- It sends plain text messages via `/v1/messages`.
- It listens for run activity through server SSE events.
- If no token is configured, start the app and use `/bootstrap` or `/pair` in the chat.
- `/bootstrap` requires server env `SKITTER_BOOTSTRAP_CODE`.
- Access token is persisted in `~/.config/skitter-tui/state.json` and reused on restart.
- Persisted token is preferred on startup; pass `--access-token` explicitly to override.
