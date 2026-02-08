from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys

from .app import AppConfig, SkitterTuiApp


def _default_user_id() -> str:
    user = getpass.getuser().strip() or "user"
    host = socket.gethostname().strip() or "localhost"
    return f"tui:{user}@{host}"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone TUI client for Skittermander API")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SKITTER_API_URL", "").strip(),
        help="Skittermander server base URL, e.g. http://localhost:8000",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("SKITTER_API_KEY", "").strip(),
        help="API key for /v1/* endpoints (or set SKITTER_API_KEY).",
    )
    parser.add_argument(
        "--user-id",
        default=os.environ.get("SKITTER_TUI_USER_ID", _default_user_id()),
        help="Stable user identifier used when creating/sending sessions",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("SKITTER_TUI_SESSION_ID", "").strip() or None,
        help="Optional existing session id to attach to",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if not args.api_url:
        print("Error: --api-url is required (or set SKITTER_API_URL).", file=sys.stderr)
        raise SystemExit(2)
    if not args.api_key:
        print("Error: --api-key is required (or set SKITTER_API_KEY).", file=sys.stderr)
        raise SystemExit(2)

    config = AppConfig(
        api_url=args.api_url,
        user_id=args.user_id,
        api_key=args.api_key or None,
        session_id=args.session_id,
    )
    app = SkitterTuiApp(config)
    app.run()


if __name__ == "__main__":
    main()
