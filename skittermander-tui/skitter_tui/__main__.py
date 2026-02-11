from __future__ import annotations

import argparse
import os
import socket
import sys

from .app import AppConfig, SkitterTuiApp


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone TUI client for Skittermander API")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("SKITTER_API_URL", "").strip(),
        help="Skittermander server base URL, e.g. http://localhost:8000",
    )
    parser.add_argument(
        "--access-token",
        "--api-key",
        dest="access_token",
        default=os.environ.get("SKITTER_API_KEY", "").strip(),
        help="Access token for /v1/* endpoints (or set SKITTER_API_KEY).",
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

    config = AppConfig(
        api_url=args.api_url,
        access_token=args.access_token or None,
        device_name=socket.gethostname().strip() or None,
        session_id=args.session_id,
    )
    app = SkitterTuiApp(config)
    app.run()


if __name__ == "__main__":
    main()
