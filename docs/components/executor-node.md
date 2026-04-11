# Executor Node

`skitter-node` is a host executor process. It connects to the API over WebSocket, receives tool requests, and runs them directly on the host with the permissions of the user account that launched it.

## Supported Hosts

- macOS, Linux, and Windows can run node executors.
- The API/WebSocket contract is the same across platforms.
- File, download, HTTP fetch, shell, patch, and browser tools use the node workspace root.
- Host-device tools are capability-gated per node: `notify`, `screenshot`, `mouse`, and `keyboard`.

## Install

macOS/Linux:

```bash
./setup.sh install-cli
```

Windows PowerShell:

```powershell
uv tool install --force --editable .
```

The Admin UI generates a token and launch command. On Windows, use a PowerShell command with an absolute workspace root:

```powershell
skitter-node --api-url "http://<api-host>:8000" --token "<token>" --name "<node-name>" --workspace-root "$env:USERPROFILE\SkitterNode\workspace" --write-config
```

Default config paths:

- macOS/Linux: `$HOME/.config/skitter-node/config.yaml`
- Windows: `%APPDATA%\skitter-node\config.yaml`

## Platform Behavior

- `shell(cmd=...)` runs through Bash or `/bin/sh` on macOS/Linux.
- `shell(cmd=...)` runs through PowerShell on Windows, preferring `pwsh` and falling back to Windows PowerShell.
- `apply_patch` uses the host `patch` command when available, and falls back to Skitter's Python unified-diff applier on Windows or hosts without `patch`.
- macOS screenshots require Screen Recording permission.
- macOS mouse and keyboard control require Accessibility permission.
- Windows screenshots use Pillow ImageGrab.
- Windows mouse and keyboard control use Win32 desktop APIs and require an interactive user session. Elevated/admin windows can only be controlled when the node is also elevated.

## Optional Browser Tools

Browser tools are optional on host nodes. On Windows, install Playwright into the same tool environment and install Chromium:

```powershell
uv tool install --force --editable . --with playwright
uv tool run --from playwright playwright install chromium
```

Set `SKITTER_BROWSER_EXECUTABLE` only when you want to force a specific browser executable.
