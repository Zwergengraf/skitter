#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: send-text.sh -t target [options] -- message

Send literal text to a tmux pane, then optionally press Enter after a short delay.

Options:
  -t, --target       tmux target (session:window.pane), required
  -L, --socket       tmux socket name (passed to tmux -L)
  -S, --socket-path  tmux socket path (passed to tmux -S)
  -d, --delay        seconds to wait before sending Enter (default: 0.1)
  -n, --no-enter     do not send Enter after the text
  -h, --help         show this help
USAGE
}

target=""
socket_name=""
socket_path=""
delay="0.1"
send_enter=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target)       target="${2-}"; shift 2 ;;
    -L|--socket)       socket_name="${2-}"; shift 2 ;;
    -S|--socket-path)  socket_path="${2-}"; shift 2 ;;
    -d|--delay)        delay="${2-}"; shift 2 ;;
    -n|--no-enter)     send_enter=false; shift ;;
    -h|--help)         usage; exit 0 ;;
    --)                shift; break ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -n "$socket_name" && -n "$socket_path" ]]; then
  echo "Use either -L or -S, not both" >&2
  exit 1
fi

if [[ -z "$target" ]]; then
  echo "target is required" >&2
  usage
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "message is required after --" >&2
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
  tmux_cmd+=(-S "$socket_path")
fi

message="$*"
"${tmux_cmd[@]}" send-keys -t "$target" -l -- "$message"
if [[ "$send_enter" == true ]]; then
  sleep "$delay"
  "${tmux_cmd[@]}" send-keys -t "$target" Enter
fi
