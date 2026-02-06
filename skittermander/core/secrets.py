from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class SecretsManager:
    def __init__(self, key: str | None = None) -> None:
        self.key = (key or os.environ.get("SKITTER_SECRETS_MASTER_KEY", "")).strip()

    def ensure_ready(self) -> None:
        if not self.key:
            raise RuntimeError("SKITTER_SECRETS_MASTER_KEY is not set")
        # Validate key format.
        try:
            Fernet(self.key)
        except Exception as exc:
            raise RuntimeError("SKITTER_SECRETS_MASTER_KEY is invalid") from exc

    def _fernet(self) -> Fernet:
        self.ensure_ready()
        return Fernet(self.key)

    def encrypt(self, value: str) -> str:
        token = self._fernet().encrypt(value.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            plain = self._fernet().decrypt(token.encode("utf-8"))
        except InvalidToken as exc:
            raise RuntimeError("Secret decryption failed") from exc
        return plain.decode("utf-8")
