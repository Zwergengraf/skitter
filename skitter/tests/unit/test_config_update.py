from __future__ import annotations

import pytest
from pydantic import ValidationError

from skitter.core.config import apply_settings_update


def test_apply_settings_update_rejects_legacy_model_layout() -> None:
    with pytest.raises(ValidationError):
        apply_settings_update(
            {
                "providers": [],
                "models": [
                    {
                        "name": "legacy-model",
                        "api_type": "openai",
                        "api_base": "http://localhost:1234/v1",
                        "api_key": "secret",
                        "model_id": "gpt-legacy",
                    }
                ],
            }
        )
