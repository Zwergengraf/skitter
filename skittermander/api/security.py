from __future__ import annotations

import hashlib
import secrets as stdlib_secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request


TOKEN_PREFIX = "sktr_tok_"
PAIR_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(slots=True)
class AuthPrincipal:
    kind: str  # "admin" | "user"
    user_id: str | None = None
    token_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"

    @property
    def is_user(self) -> bool:
        return self.kind == "user" and self.user_id is not None


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_client_token() -> str:
    return TOKEN_PREFIX + stdlib_secrets.token_urlsafe(36)


def token_prefix(token: str) -> str:
    if token.startswith(TOKEN_PREFIX):
        return token[: min(len(token), len(TOKEN_PREFIX) + 8)]
    return token[:12]


def make_pair_code() -> str:
    chars = [PAIR_CODE_ALPHABET[stdlib_secrets.randbelow(len(PAIR_CODE_ALPHABET))] for _ in range(8)]
    return f"{''.join(chars[:4])}-{''.join(chars[4:])}"


def normalize_pair_code(raw: str) -> str:
    return (raw or "").strip().upper().replace("-", "")


def hash_pair_code(raw: str) -> str:
    return hash_secret(normalize_pair_code(raw))


def extract_credential(request: Request) -> str:
    provided = (request.headers.get("x-api-key") or "").strip()
    if provided:
        return provided
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def get_auth_principal(request: Request) -> AuthPrincipal:
    principal = getattr(request.state, "auth_principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def require_user_principal(request: Request) -> AuthPrincipal:
    principal = get_auth_principal(request)
    if not principal.is_user:
        raise HTTPException(status_code=403, detail="User token required")
    return principal


def require_admin_principal(request: Request) -> AuthPrincipal:
    principal = get_auth_principal(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin API key required")
    return principal
