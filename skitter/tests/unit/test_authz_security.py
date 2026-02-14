from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from skitter.api.authz import require_authenticated_user, resolve_target_user_id
from skitter.api.security import AuthPrincipal, extract_credential


class _Request:
    def __init__(self, headers: dict[str, str] | None = None, principal: AuthPrincipal | None = None) -> None:
        self.headers = headers or {}
        self.state = SimpleNamespace(auth_principal=principal)


def test_extract_credential_prefers_x_api_key() -> None:
    request = _Request(headers={"x-api-key": "key-1", "authorization": "Bearer key-2"})
    assert extract_credential(request) == "key-1"


def test_extract_credential_falls_back_to_bearer() -> None:
    request = _Request(headers={"authorization": "Bearer token-1"})
    assert extract_credential(request) == "token-1"


def test_resolve_target_user_id_for_admin_and_user() -> None:
    admin_request = _Request(principal=AuthPrincipal(kind="admin"))
    assert resolve_target_user_id(admin_request, "user-1") == "user-1"

    with pytest.raises(HTTPException) as admin_exc:
        resolve_target_user_id(admin_request, None)
    assert admin_exc.value.status_code == 400

    user_request = _Request(principal=AuthPrincipal(kind="user", user_id="user-1"))
    assert resolve_target_user_id(user_request, None) == "user-1"
    assert resolve_target_user_id(user_request, "user-1") == "user-1"

    with pytest.raises(HTTPException) as user_exc:
        resolve_target_user_id(user_request, "user-2")
    assert user_exc.value.status_code == 403


def test_require_authenticated_user_rejects_admin_without_user_context() -> None:
    request = _Request(principal=AuthPrincipal(kind="admin"))
    with pytest.raises(HTTPException) as exc:
        require_authenticated_user(request)
    assert exc.value.status_code == 400
