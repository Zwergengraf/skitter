# Skittermander TUI (Standalone)

A standalone terminal UI client for interacting with a remote Skittermander server over HTTP/SSE.

## Features

- Separate project outside the main `skittermander/` server code.
- Creates sessions and sends messages through the API.
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
skitter-tui --api-url http://localhost:8000 --api-key <YOUR_API_KEY> --user-id gabriel-local
```

Or with env vars:

```bash
export SKITTER_API_URL=http://localhost:8000
export SKITTER_API_KEY=<YOUR_API_KEY>
export SKITTER_TUI_USER_ID=gabriel-local
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
