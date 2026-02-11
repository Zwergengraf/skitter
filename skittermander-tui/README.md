# Skittermander TUI (Standalone)

A standalone terminal UI client for interacting with a remote Skittermander server over HTTP/SSE.

## Features

- Separate project outside the main `skittermander/` server code.
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
  - `/new` create a new session
  - `/session` show active session
  - `/whoami` show authenticated user
  - `/bootstrap <setup_code> <display_name>` first-time setup
  - `/pair <pair_code>` pair with existing account (e.g. via Discord `/pair`)
  - `/token <access_token>` set token manually
  - `/logout` clear token
  - `/attachments` list attachments from the last assistant reply
  - `/download <index> [target_path]` download one attachment
  - `/clear` clear local chat view
  - `/help` show help
  - `/quit` exit

## Requirements

- Python `>=3.11`
- Reachable Skittermander API server

## Install

```bash
cd /Users/gabriel/Code/Skittermander/skittermander-tui
python -m venv .venv
source .venv/bin/activate
pip install -e .
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
