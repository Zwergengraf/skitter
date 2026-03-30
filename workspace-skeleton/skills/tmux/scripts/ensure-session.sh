#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ensure-session.sh -s session [options]

Create a detached tmux session if missing, otherwise do nothing.

Options:
  -s, --session      session name, required
  -L, --socket       tmux socket name (passed to tmux -L)
  -S, --socket-path  tmux socket path (passed to tmux -S)
  -n, --window-name  initial window name (default: shell)
  -h, --help         show this help
USAGE
}

session_name=""
socket_name=""
socket_path=""
window_name="shell"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--session)      session_name="${2-}"; shift 2 ;;
    -L|--socket)       socket_name="${2-}"; shift 2 ;;
    -S|--socket-path)  socket_path="${2-}"; shift 2 ;;
    -n|--window-name)  window_name="${2-}"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -n "$socket_name" && -n "$socket_path" ]]; then
  echo "Use either -L or -S, not both" >&2
  exit 1
fi

if [[ -z "$session_name" ]]; then
  echo "session name is required" >&2
  usage
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not found in PATH" >&2
  exit 1
fi

tmux_cmd=(tmux)
if [[ -n "$socket_name" ]]; then
  tmux_cmd+=(-L "$socket_name")
elif [[ -n "$socket_path" ]]; then
  mkdir -p "$(dirname "$socket_path")"
  tmux_cmd+=(-S "$socket_path")
fi

if "${tmux_cmd[@]}" has-session -t "$session_name" 2>/dev/null; then
  echo "Session '$session_name' already exists"
  exit 0
fi

"${tmux_cmd[@]}" new-session -d -s "$session_name" -n "$window_name"
echo "Created session '$session_name'"
