from __future__ import annotations

from fastapi import Depends

from ..data.db import get_session
from ..data.repositories import Repository


def get_repo(session=Depends(get_session)) -> Repository:
    return Repository(session)
