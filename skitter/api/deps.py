from __future__ import annotations

from fastapi import Depends, Request

from ..data.db import get_session
from ..data.repositories import Repository


def get_repo(request: Request, session=Depends(get_session)) -> Repository:
    repo = Repository(session)
    session.info["runtime"] = request.app.state.runtime
    return repo
