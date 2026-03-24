from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import skitter.sandbox.runner as runner_module
from skitter.sandbox.runner import create_app


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


@pytest.mark.asyncio
async def test_runner_apply_patch_updates_file_with_plain_relative_paths(
    runner_workspace: tuple[Path, object]
) -> None:
    workspace_root, app = runner_workspace
    target = workspace_root / "hello.txt"
    target.write_text("old\n", encoding="utf-8")
    patch = "".join(
        difflib.unified_diff(
            ["old\n"],
            ["new\n"],
            fromfile="hello.txt",
            tofile="hello.txt",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _execute(client, tool="apply_patch", payload={"patch": patch})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["exit_code"] == 0
    assert body["strip"] == 0
    assert "patching file hello.txt" in body["stdout"]
    assert target.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_runner_apply_patch_uses_git_style_strip_level(
    runner_workspace: tuple[Path, object]
) -> None:
    workspace_root, app = runner_workspace
    target = workspace_root / "src" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('old')\n", encoding="utf-8")
    patch = "".join(
        difflib.unified_diff(
            ["print('old')\n"],
            ["print('new')\n"],
            fromfile="a/src/main.py",
            tofile="b/src/main.py",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _execute(client, tool="apply_patch", payload={"patch": patch})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["exit_code"] == 0
    assert body["strip"] == 1
    assert "src/main.py" in body["stdout"]
    assert target.read_text(encoding="utf-8") == "print('new')\n"


@pytest.mark.asyncio
async def test_runner_notify_routes_to_host_notification_helper(
    runner_workspace: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, app = runner_workspace

    async def fake_notify(payload: dict) -> dict:
        assert payload["title"] == "Skitter"
        assert payload["message"] == "Done"
        return {"status": "ok", "title": "Skitter", "message": "Done"}

    monkeypatch.setattr(runner_module, "_execute_notify", fake_notify)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _execute(client, tool="notify", payload={"title": "Skitter", "message": "Done"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_runner_screenshot_routes_to_host_screenshot_helper(
    runner_workspace: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, app = runner_workspace

    async def fake_screenshot(workspace_root: Path, session_id: str, payload: dict) -> dict:
        assert workspace_root.name == "workspace"
        assert session_id == "session-1"
        assert payload == {}
        return {"status": "ok", "screenshot_path": "screenshots/session-1/test.png"}

    monkeypatch.setattr(runner_module, "_execute_screenshot", fake_screenshot)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _execute(client, tool="screenshot", payload={})

    assert response.status_code == 200
    assert response.json()["screenshot_path"] == "screenshots/session-1/test.png"


@pytest.mark.asyncio
async def test_runner_mouse_and_keyboard_tools_route_to_helpers(
    runner_workspace: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, app = runner_workspace

    async def fake_mouse_move(payload: dict) -> dict:
        assert payload == {"x": 12, "y": 34}
        return {"status": "ok", "x": 12, "y": 34}

    async def fake_mouse_click(payload: dict) -> dict:
        assert payload["button"] == "left"
        return {"status": "ok", "x": 12, "y": 34}

    async def fake_keyboard_type(payload: dict) -> dict:
        assert payload["text"] == "hello"
        return {"status": "ok"}

    async def fake_keyboard_press(payload: dict) -> dict:
        assert payload["key"] == "enter"
        assert payload["modifiers"] == ["cmd"]
        return {"status": "ok"}

    monkeypatch.setattr(runner_module, "_execute_mouse_move", fake_mouse_move)
    monkeypatch.setattr(runner_module, "_execute_mouse_click", fake_mouse_click)
    monkeypatch.setattr(runner_module, "_execute_keyboard_type", fake_keyboard_type)
    monkeypatch.setattr(runner_module, "_execute_keyboard_press", fake_keyboard_press)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        move_resp = await _execute(client, tool="mouse_move", payload={"x": 12, "y": 34})
        click_resp = await _execute(client, tool="mouse_click", payload={"x": 12, "y": 34, "button": "left"})
        type_resp = await _execute(client, tool="keyboard_type", payload={"text": "hello"})
        press_resp = await _execute(
            client,
            tool="keyboard_press",
            payload={"key": "enter", "modifiers": ["cmd"]},
        )

    assert move_resp.status_code == 200
    assert click_resp.status_code == 200
    assert type_resp.status_code == 200
    assert press_resp.status_code == 200
