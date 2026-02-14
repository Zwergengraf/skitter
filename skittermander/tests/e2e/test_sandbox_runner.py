from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from skittermander.sandbox.runner import create_app


@pytest.fixture
def runner_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, object]:
    workspace_root = tmp_path / "workspace"
    browser_root = tmp_path / "browser-data"
    monkeypatch.setenv("SKITTER_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("SKITTER_BROWSER_DATA_ROOT", str(browser_root))
    app = create_app()
    return workspace_root, app


async def _execute(
    client: AsyncClient,
    *,
    tool: str,
    payload: dict,
    session_id: str = "session-1",
):
    response = await client.post(
        "/execute",
        json={"session_id": session_id, "tool": tool, "payload": payload},
    )
    return response


@pytest.mark.asyncio
async def test_runner_list_hides_hidden_files_by_default(runner_workspace: tuple[Path, object]) -> None:
    workspace_root, app = runner_workspace
    (workspace_root / "public.txt").write_text("ok", encoding="utf-8")
    (workspace_root / ".secret").write_text("hidden", encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        default_resp = await _execute(client, tool="list", payload={"path": "."})
        assert default_resp.status_code == 200
        assert default_resp.json()["entries"] == ["public.txt"]

        show_hidden_resp = await _execute(
            client,
            tool="list",
            payload={"path": ".", "show_hidden_files": True},
        )
        assert show_hidden_resp.status_code == 200
        assert show_hidden_resp.json()["entries"] == [".secret", "public.txt"]


@pytest.mark.asyncio
async def test_runner_read_image_returns_workspace_local_file_path(
    runner_workspace: tuple[Path, object]
) -> None:
    workspace_root, app = runner_workspace
    image = workspace_root / "avatars" / "zig.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"\x89PNG\r\n")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _execute(
            client,
            tool="read",
            payload={"path": "avatars/zig.png"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["file_path"] == "avatars/zig.png"
    assert body["content_type"] == "image/png"


@pytest.mark.asyncio
async def test_runner_relative_and_absolute_path_writes(runner_workspace: tuple[Path, object], tmp_path: Path) -> None:
    workspace_root, app = runner_workspace
    external_target = tmp_path / "outside.txt"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        relative = await _execute(
            client,
            tool="write",
            payload={"path": "notes/todo.txt", "content": "hello"},
        )
        assert relative.status_code == 200
        assert (workspace_root / "notes" / "todo.txt").read_text(encoding="utf-8") == "hello"

        absolute = await _execute(
            client,
            tool="write",
            payload={"path": str(external_target), "content": "outside"},
        )
        assert absolute.status_code == 200
        assert external_target.read_text(encoding="utf-8") == "outside"


@pytest.mark.asyncio
async def test_runner_shell_supports_multiline_bash_script(runner_workspace: tuple[Path, object]) -> None:
    _, app = runner_workspace
    if not Path("/bin/bash").exists():
        pytest.skip("requires /bin/bash for pipefail support")

    script = "set -eo pipefail\nprintf 'alpha\\n' | grep alpha >/dev/null\nprintf done"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _execute(client, tool="shell", payload={"cmd": script})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["exit_code"] == 0
    assert "done" in body["stdout"]
