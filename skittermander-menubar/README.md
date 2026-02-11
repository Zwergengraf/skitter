# Skittermander macOS Menu Bar App (MVP)

Native macOS menu bar companion for your Skittermander API server.

## Implemented in this MVP

- Menu bar status icon:
  - healthy
  - API error
  - thinking / active tasks
- Left-click menu bar icon opens a chat panel under the menu bar.
- Right-click menu bar icon opens menu with:
  - status line
  - context length bar
  - current session cost
  - settings window
  - about window
  - quit
- Chat panel talks to your API (`/v1/sessions`, `/v1/messages`) and resumes menubar session history.

## Requirements

- macOS 14+
- Xcode / Swift toolchain
- Running Skittermander server with auth configured:
  - `SKITTER_API_KEY` (admin key)
  - `SKITTER_BOOTSTRAP_CODE` (for first-device bootstrap)

## Run

```bash
cd ./skittermander-menubar
swift build
swift run
```

## Install locally + autostart on login

```bash
cd ./skittermander-menubar
chmod +x ./install-menubar.sh
./install-menubar.sh install
```

Useful commands:

```bash
./install-menubar.sh status
./install-menubar.sh uninstall
```

## First-time setup (new auth flow)

Open menu bar icon -> right click -> `Settings` and set:

- API URL (`http://localhost:8000` by default)
- Access Token (optional if you already have one)
- context bar target tokens

Then choose one login path:

1. Register first account (no Discord required):
- Enter `Display Name`
- Enter `Setup Code` (`SKITTER_BOOTSTRAP_CODE` from server env)
- Click `Register & Connect`

2. Pair existing account:
- Get a pair code from an already authenticated client (e.g. Discord `/pair`)
- Enter `Pair Code`
- Click `Pair Existing Account`

After login:
- account setup fields are hidden
- `Logout` is available in settings

## Notes

- This is a lean MVP so we can validate UX quickly.
- Voice input/wake word and macOS control tools are intentionally not included yet.
