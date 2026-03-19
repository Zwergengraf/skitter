from __future__ import annotations

import asyncio
import os
import base64
import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime

try:
    from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - optional dependency on host nodes
    async_playwright = None
    BrowserContext = Any  # type: ignore[assignment]
    Page = Any  # type: ignore[assignment]

    class PlaywrightTimeoutError(Exception):
        pass


class ExecuteRequest(BaseModel):
    session_id: str
    tool: str
    payload: Dict[str, Any]


class TaskStatusRequest(BaseModel):
    pids: list[int]


_playwright = None
_contexts: dict[str, BrowserContext] = {}
_pages: dict[str, Page] = {}
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(profile_id: str) -> asyncio.Lock:
    lock = _locks.get(profile_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[profile_id] = lock
    return lock


def _safe_session(session_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id)


def _browser_profile_key(session_id: str) -> str:
    # Use a stable profile per sandbox container (per user).
    return "default"


def _save_screenshot(workspace_root: Path, session_id: str, png: bytes) -> str:
    shots_root = workspace_root / "screenshots" / _safe_session(session_id)
    shots_root.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.png"
    path = shots_root / filename
    path.write_bytes(png)
    return str(Path("screenshots") / _safe_session(session_id) / filename)


def _clear_browser_locks(data_dir: Path) -> None:
    print(f"Clearing browser locks in {data_dir}")
    # Clear Chromium profile locks that can remain after a crash/restart.
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            lock_path = data_dir / name
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            continue


def _clear_all_browser_locks(browser_data_root: Path) -> None:
    print(f"Clearing all browser locks in {browser_data_root}")
    if not browser_data_root.exists():
        return
    for child in browser_data_root.iterdir():
        if child.is_dir():
            _clear_browser_locks(child)


async def _get_context(
    profile_id: str, browser_data_root: Path, width: int, height: int, executable: str | None
) -> BrowserContext:
    global _playwright
    if async_playwright is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Browser tools are unavailable: Playwright is not installed on this executor node. "
                "Install `playwright` and browser binaries to enable browser/browser_action."
            ),
        )
    if _playwright is None:
        _playwright = await async_playwright().start()
    if profile_id in _contexts:
        return _contexts[profile_id]
    data_dir = browser_data_root / _safe_session(profile_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=str(data_dir),
        viewport={"width": width, "height": height},
        executable_path=executable,
        args=["--disable-dev-shm-usage"],
    )
    _contexts[profile_id] = context
    return context


async def _get_page(profile_id: str, context: BrowserContext) -> Page:
    if profile_id in _pages:
        return _pages[profile_id]
    pages = context.pages
    page = pages[0] if pages else await context.new_page()
    _pages[profile_id] = page
    return page


async def _capture_page_screenshot(page: Page, *, full_page: bool, timeout_ms: int) -> bytes:
    # Improve stability on host executors where first-frame captures can be blank.
    try:
        await page.bring_to_front()
    except Exception:
        pass
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 10000))
    except Exception:
        pass
    await page.wait_for_timeout(350)

    png = await page.screenshot(full_page=full_page, timeout=timeout_ms)
    if full_page:
        # Fallback: on some sites/browsers full-page captures can be blank while viewport capture is valid.
        try:
            viewport_png = await page.screenshot(full_page=False, timeout=timeout_ms)
            if len(viewport_png) > len(png) * 2:
                png = viewport_png
        except Exception:
            pass
    return png


def create_app() -> FastAPI:
    workspace_root = Path(os.environ.get("SKITTER_WORKSPACE_ROOT", "/tmp/skitter-workspace"))
    workspace_root.mkdir(parents=True, exist_ok=True)
    browser_root_default = workspace_root / ".browser-data"
    browser_data_root = Path(os.environ.get("SKITTER_BROWSER_DATA_ROOT", str(browser_root_default)))
    try:
        browser_data_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        browser_data_root = browser_root_default
        browser_data_root.mkdir(parents=True, exist_ok=True)
    browser_executable = os.environ.get("SKITTER_BROWSER_EXECUTABLE") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _clear_all_browser_locks(browser_data_root)
        yield

    app = FastAPI(title="Skitter Sandbox", lifespan=lifespan)

    def safe_path(path: str) -> Path:
        value = str(path or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail="path is required")
        raw = Path(value)
        if raw.is_absolute():
            # Keep absolute paths literal; do not resolve symlinks.
            return raw
        # Relative paths are anchored at workspace root.
        return workspace_root / raw

    def _payload_path(payload: Dict[str, Any]) -> str:
        return payload.get("path") or payload.get("file_path") or ""

    def _detect_patch_strip_count(patch_text: str) -> int:
        for raw_line in patch_text.splitlines():
            if raw_line.startswith("--- ") or raw_line.startswith("+++ "):
                candidate = raw_line[4:].strip()
                if not candidate or candidate == "/dev/null":
                    continue
                header_path = candidate.split("\t", 1)[0].strip()
                if header_path.startswith(("a/", "b/")):
                    return 1
                return 0
        return 0

    def _workspace_response_path(target: Path) -> str:
        try:
            rel = target.relative_to(workspace_root)
        except ValueError:
            return str(target).replace("\\", "/")
        rel_str = str(rel).replace("\\", "/")
        if rel_str in {"", "."}:
            return "."
        # Return workspace-local paths (relative to /workspace root), not pseudo-absolute paths.
        return rel_str.lstrip("/")

    def _read_text_file(
        target: Path, offset: int | None, limit: int | None, max_lines: int = 2000, max_bytes: int = 50 * 1024
    ) -> dict[str, Any]:
        start_line = max(1, offset or 1)
        remaining_lines = max_lines
        if limit is not None:
            remaining_lines = max(1, min(max_lines, int(limit)))
        collected: list[str] = []
        bytes_count = 0
        read_lines = 0
        truncated = False
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle, start=1):
                if idx < start_line:
                    continue
                if read_lines >= remaining_lines:
                    truncated = True
                    break
                encoded = line.encode("utf-8")
                if bytes_count + len(encoded) > max_bytes:
                    truncated = True
                    break
                collected.append(line)
                bytes_count += len(encoded)
                read_lines += 1
        content = "".join(collected)
        next_offset = start_line + read_lines if truncated else None
        return {
            "status": "ok",
            "content": content,
            "truncated": truncated,
            "next_offset": next_offset,
        }

    def _read_file_base64(target: Path, *, max_bytes: int = 12 * 1024 * 1024) -> dict[str, Any]:
        size = target.stat().st_size
        if size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large to read as base64 ({size} bytes > {max_bytes} bytes)",
            )
        raw = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(target.name)
        return {
            "status": "ok",
            "file_path": _workspace_response_path(target),
            "content_type": mime_type or "application/octet-stream",
            "size": len(raw),
            "base64": base64.b64encode(raw).decode("ascii"),
        }

    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _read_process_state(proc_dir: Path) -> str:
        try:
            stat_raw = (proc_dir / "stat").read_text(encoding="utf-8", errors="replace")
            # Linux /proc/<pid>/stat format: "<pid> (<comm>) <state> ..."
            tail = stat_raw.split(") ", 1)
            if len(tail) < 2:
                return "?"
            return tail[1].split(" ", 1)[0]
        except OSError:
            return "?"

    def _read_process_cmdline(proc_dir: Path) -> str:
        try:
            raw = (proc_dir / "cmdline").read_bytes()
        except OSError:
            return ""
        if not raw:
            return ""
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()

    def _is_internal_process(cmdline: str) -> bool:
        lowered = cmdline.lower()
        # Playwright driver and Chromium/Brave helper processes are internal runtime infrastructure.
        internal_markers = (
            "playwright/driver/package/cli.js run-driver",
            "/playwright/driver/node",
            "chrome_crashpad_handler",
            "--type=zygote",
            "--type=gpu-process",
            "--type=utility",
            "--type=renderer",
            "--remote-debugging-pipe",
            "chromium",
            "brave-browser",
        )
        return any(marker in lowered for marker in internal_markers)

    def _list_non_runner_processes() -> list[dict[str, Any]]:
        proc_root = Path("/proc")
        self_pid = os.getpid()
        results: list[dict[str, Any]] = []
        if not proc_root.exists():
            return results
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
            except ValueError:
                continue
            if pid == self_pid:
                continue
            state = _read_process_state(entry)
            if state == "Z":
                continue
            cmdline = _read_process_cmdline(entry)
            if not cmdline:
                continue
            if _is_internal_process(cmdline):
                continue
            results.append({"pid": pid, "state": state, "cmdline": cmdline})
        return results

    @app.post("/execute")
    async def execute(req: ExecuteRequest):
        if req.tool in {"read", "write", "edit", "list", "delete"}:
            path = _payload_path(req.payload)
            if not path:
                raise HTTPException(status_code=400, detail="path is required")
            target = safe_path(path)
            if req.tool == "read":
                if not target.exists():
                    raise HTTPException(status_code=404, detail="File not found")
                if target.is_dir():
                    raise HTTPException(status_code=400, detail="Path is a directory")
                include_base64 = bool(req.payload.get("include_base64", False))
                if include_base64:
                    return _read_file_base64(target)
                ext = target.suffix.lower()
                if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    content_type = "image/jpeg" if ext in {".jpg", ".jpeg"} else f"image/{ext.lstrip('.')}"
                    response = {
                        "status": "ok",
                        "file_path": _workspace_response_path(target),
                        "content_type": content_type,
                    }
                    return response
                offset = _coerce_int(req.payload.get("offset"))
                limit = _coerce_int(req.payload.get("limit"))
                return _read_text_file(target, offset=offset, limit=limit)
            if req.tool == "write":
                overwrite = bool(req.payload.get("overwrite", True))
                if target.exists() and not overwrite:
                    raise HTTPException(status_code=409, detail="Target already exists")
                target.parent.mkdir(parents=True, exist_ok=True)
                base64_content = req.payload.get("base64")
                if base64_content is not None:
                    try:
                        raw = base64.b64decode(str(base64_content), validate=True)
                    except Exception as exc:
                        raise HTTPException(status_code=400, detail="Invalid base64 payload") from exc
                    target.write_bytes(raw)
                    return {
                        "status": "ok",
                        "path": _workspace_response_path(target),
                        "bytes_written": len(raw),
                        "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                    }
                content = req.payload.get("content")
                if content is None:
                    raise HTTPException(status_code=400, detail="content or base64 is required")
                encoded = str(content)
                target.write_text(encoded, encoding="utf-8")
                return {
                    "status": "ok",
                    "path": _workspace_response_path(target),
                    "bytes_written": len(encoded.encode("utf-8")),
                    "content_type": "text/plain",
                }
            if req.tool == "edit":
                old_text = req.payload.get("oldText") or req.payload.get("old_string")
                new_text = req.payload.get("newText") or req.payload.get("new_string")
                if old_text is None:
                    raise HTTPException(status_code=400, detail="oldText is required")
                if new_text is None:
                    raise HTTPException(status_code=400, detail="newText is required")
                if not target.exists():
                    raise HTTPException(status_code=404, detail="File not found")
                if target.is_dir():
                    raise HTTPException(status_code=400, detail="Path is a directory")
                content = target.read_text(encoding="utf-8", errors="replace")
                count = content.count(old_text)
                if count == 0:
                    raise HTTPException(status_code=400, detail="oldText not found")
                updated = content.replace(old_text, new_text)
                target.write_text(updated, encoding="utf-8")
                return {"status": "ok", "replacements": count}
            if req.tool == "list":
                if not target.exists():
                    raise HTTPException(status_code=404, detail="Path not found")
                show_hidden = bool(req.payload.get("show_hidden_files", False))
                entries = []
                for p in target.iterdir():
                    if not show_hidden and p.name.startswith("."):
                        continue
                    entries.append(p.name)
                entries.sort()
                return {"status": "ok", "entries": entries}
            if req.tool == "delete":
                if not target.exists():
                    return {"status": "ok", "deleted": False}
                if target.is_dir():
                    if req.payload.get("recursive"):
                        shutil.rmtree(target)
                    else:
                        target.rmdir()
                else:
                    target.unlink()
                return {"status": "ok", "deleted": True}
            raise HTTPException(status_code=400, detail="Unknown filesystem tool")

        if req.tool == "apply_patch":
            patch_text = req.payload.get("patch")
            if patch_text is None or str(patch_text).strip() == "":
                raise HTTPException(status_code=400, detail="patch is required")
            cwd = req.payload.get("cwd", "")
            working_dir = safe_path(cwd) if cwd else workspace_root
            if not working_dir.exists():
                raise HTTPException(status_code=404, detail="cwd not found")
            if not working_dir.is_dir():
                raise HTTPException(status_code=400, detail="cwd is not a directory")
            strip_count = _detect_patch_strip_count(str(patch_text))
            argv = [
                "patch",
                "--batch",
                "--forward",
                "--reject-file=-",
                f"-p{strip_count}",
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=str(working_dir),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=503, detail="patch command is not available on this executor") from exc
            stdout, stderr = await proc.communicate(str(patch_text).encode("utf-8"))

            def _trim_patch_output(data: bytes) -> str:
                return data.decode("utf-8", errors="replace")[:12000]

            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": _trim_patch_output(stdout),
                "stderr": _trim_patch_output(stderr),
                "cwd": _workspace_response_path(working_dir),
                "strip": strip_count,
            }

        if req.tool == "http_fetch":
            url = req.payload.get("url")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                return {"status": "ok", "status_code": resp.status_code, "body": resp.text[:10000]}

        if req.tool == "download":
            url = req.payload.get("url")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                raise HTTPException(status_code=400, detail="url must start with http or https")
            path = req.payload.get("path")
            if path:
                target = safe_path(str(path))
            else:
                filename = Path(parsed.path).name or "download.bin"
                date_dir = datetime.utcnow().strftime("%Y-%m-%d")
                target = safe_path(str(Path("downloads") / date_dir / filename))
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            content_type = ""
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    content_type = resp.headers.get("Content-Type", "") or ""
                    with target.open("wb") as handle:
                        async for chunk in resp.aiter_bytes():
                            handle.write(chunk)
                            size += len(chunk)
            return {
                "status": "ok",
                "path": _workspace_response_path(target),
                "content_type": content_type,
                "size": size,
            }

        if req.tool == "shell":
            cmd = req.payload.get("cmd")
            args = req.payload.get("args")
            cwd = req.payload.get("cwd", "")
            background = bool(req.payload.get("background", False))
            log_path = req.payload.get("log_path")
            env_payload = req.payload.get("env") or {}
            redact_values = req.payload.get("redact") or []
            if not cmd and not args:
                raise HTTPException(status_code=400, detail="cmd or args is required")
            working_dir = safe_path(cwd) if cwd else workspace_root

            if args:
                argv = [str(arg) for arg in args]
            else:
                shell_path = "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"
                argv = [shell_path, "-lc", str(cmd)]

            try:
                env = os.environ.copy()
                if isinstance(env_payload, dict):
                    for key, value in env_payload.items():
                        env[str(key)] = str(value)
                if background:
                    stdout_target = asyncio.subprocess.DEVNULL
                    stderr_target = asyncio.subprocess.DEVNULL
                    log_target_path = None
                    log_file = None
                    if log_path:
                        log_target_path = safe_path(log_path)
                        log_target_path.parent.mkdir(parents=True, exist_ok=True)
                        log_file = open(log_target_path, "ab")
                        stdout_target = log_file
                        stderr_target = log_file
                    proc = await asyncio.create_subprocess_exec(
                        *argv,
                        cwd=str(working_dir),
                        env=env,
                        stdout=stdout_target,
                        stderr=stderr_target,
                    )
                    if log_file is not None:
                        log_file.close()
                    return {
                        "status": "running",
                        "pid": proc.pid,
                        "log_path": str(log_target_path) if log_target_path else None,
                    }
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=str(working_dir),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                except asyncio.TimeoutError:
                    proc.kill()
                    return {"status": "timeout", "exit_code": None, "stdout": "", "stderr": "Timed out"}
            except FileNotFoundError as exc:
                raise HTTPException(status_code=400, detail=f"Command not found: {exc}") from exc

            def _redact(text: str) -> str:
                if not redact_values:
                    return text
                result = text
                for value in redact_values:
                    if value:
                        result = result.replace(str(value), "[REDACTED]")
                return result

            def _trim(data: bytes) -> str:
                text = data.decode("utf-8", errors="replace")
                return _redact(text[:10000])

            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "exit_code": proc.returncode,
                "stdout": _trim(stdout),
                "stderr": _trim(stderr),
            }

        if req.tool == "browser":
            url = req.payload.get("url")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")
            max_chars = int(req.payload.get("max_chars", 20000))
            take_screenshot = bool(req.payload.get("screenshot", False))
            width = int(req.payload.get("width", 1920))
            height = int(req.payload.get("height", 1080))
            timeout_ms = int(req.payload.get("timeout_ms", 30000))
            wait_until = req.payload.get("wait_until", "networkidle")
            profile_id = _browser_profile_key(req.session_id)
            async with _get_lock(profile_id):
                context = await _get_context(profile_id, browser_data_root, width, height, browser_executable)
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                    title = await page.title()
                    html = await page.content()
                    html = html[:max_chars]
                    screenshot_path = None
                    if take_screenshot:
                        png = await _capture_page_screenshot(page, full_page=True, timeout_ms=timeout_ms)
                        screenshot_path = _save_screenshot(workspace_root, req.session_id, png)
                    return {"status": "ok", "title": title, "html": html, "screenshot_path": screenshot_path}
                except PlaywrightTimeoutError:
                    return {"status": "timeout", "detail": f"Timeout navigating to {url}"}
                finally:
                    await page.close()

        if req.tool == "browser_action":
            action = req.payload.get("action")
            session_id = req.session_id
            profile_id = _browser_profile_key(session_id)
            if not action:
                raise HTTPException(status_code=400, detail="action is required")

            width = int(req.payload.get("width", 1920))
            height = int(req.payload.get("height", 1080))
            selector = req.payload.get("selector")
            url = req.payload.get("url")
            text = req.payload.get("text", "")
            script = req.payload.get("script")
            eval_arg = req.payload.get("arg")
            x = req.payload.get("x")
            y = req.payload.get("y")
            button = str(req.payload.get("button", "left")).lower()
            click_count = int(req.payload.get("click_count", 1))
            mouse_steps = max(1, int(req.payload.get("mouse_steps", 15)))
            timeout_ms = int(req.payload.get("timeout_ms", 30000))
            wait_until = req.payload.get("wait_until", "domcontentloaded")
            full_page = bool(req.payload.get("full_page", True))
            max_chars = int(req.payload.get("max_chars", 20000))
            include_elements = bool(req.payload.get("include_elements", False))
            max_elements = int(req.payload.get("max_elements", 50))
            if button not in {"left", "right", "middle"}:
                raise HTTPException(status_code=400, detail="button must be left, right, or middle")

            async def _locator_for_pointer_target():
                if selector:
                    return page.locator(selector).first
                text_value = str(text).strip() if text is not None else ""
                if text_value:
                    return page.get_by_text(text_value).first
                return None

            async def _pointer_xy_from_payload_or_target() -> tuple[float, float]:
                if x is not None and y is not None:
                    return float(x), float(y)
                locator = await _locator_for_pointer_target()
                if locator is None:
                    raise HTTPException(
                        status_code=400,
                        detail="provide x+y coordinates or selector/text target",
                    )
                try:
                    await locator.wait_for(state="visible", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    pass
                try:
                    await locator.scroll_into_view_if_needed(timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    pass
                box = await locator.bounding_box()
                if not box:
                    raise HTTPException(status_code=400, detail="target element has no visible bounding box")
                return float(box["x"] + (box["width"] / 2.0)), float(box["y"] + (box["height"] / 2.0))

            async with _get_lock(profile_id):
                context = await _get_context(profile_id, browser_data_root, width, height, browser_executable)
                page = await _get_page(profile_id, context)
                await page.set_viewport_size({"width": width, "height": height})

                if action in {"open", "navigate"}:
                    if not url:
                        raise HTTPException(status_code=400, detail="url is required")
                    try:
                        await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                    except PlaywrightTimeoutError as exc:
                        raise HTTPException(status_code=400, detail=f"Timeout navigating to {url}") from exc
                    return {"status": "ok", "url": page.url}

                if action == "tabs":
                    tabs = []
                    for idx, tab in enumerate(context.pages):
                        tabs.append({"index": idx, "url": tab.url})
                    return {"status": "ok", "tabs": tabs}

                if action == "focus":
                    index = req.payload.get("index")
                    if index is None:
                        raise HTTPException(status_code=400, detail="index is required")
                    try:
                        tab = context.pages[int(index)]
                    except (IndexError, ValueError) as exc:
                        raise HTTPException(status_code=400, detail="invalid tab index") from exc
                    _pages[profile_id] = tab
                    await tab.bring_to_front()
                    return {"status": "ok", "url": tab.url}

                if action == "close_tab":
                    index = req.payload.get("index")
                    if index is None:
                        raise HTTPException(status_code=400, detail="index is required")
                    try:
                        tab = context.pages[int(index)]
                    except (IndexError, ValueError) as exc:
                        raise HTTPException(status_code=400, detail="invalid tab index") from exc
                    await tab.close()
                    pages = context.pages
                    _pages[profile_id] = pages[0] if pages else await context.new_page()
                    return {"status": "ok"}

                if action == "click":
                    if x is not None and y is not None:
                        click_x, click_y = float(x), float(y)
                        await page.mouse.move(click_x, click_y, steps=mouse_steps)
                        await page.mouse.click(click_x, click_y, button=button, click_count=max(1, click_count))
                        return {"status": "ok", "x": click_x, "y": click_y, "mode": "coordinates"}
                    locator = await _locator_for_pointer_target()
                    if locator is None:
                        raise HTTPException(
                            status_code=400,
                            detail="selector or text is required (or provide x+y coordinates)",
                        )
                    try:
                        await locator.wait_for(state="visible", timeout=timeout_ms)
                    except PlaywrightTimeoutError:
                        # Continue; element might still be clickable even if visibility check timed out.
                        pass
                    try:
                        await locator.scroll_into_view_if_needed(timeout=timeout_ms)
                    except PlaywrightTimeoutError:
                        pass
                    try:
                        await locator.click(timeout=timeout_ms, button=button, click_count=max(1, click_count))
                        return {"status": "ok", "mode": "locator"}
                    except PlaywrightTimeoutError:
                        # Try a forced click in case overlays or animations block normal actionability.
                        try:
                            await locator.click(
                                timeout=timeout_ms,
                                force=True,
                                button=button,
                                click_count=max(1, click_count),
                            )
                            return {"status": "ok", "forced": True, "mode": "locator"}
                        except PlaywrightTimeoutError as exc:
                            target = selector if selector else f"text:{text}"
                            raise HTTPException(
                                status_code=400, detail=f"Timeout clicking target: {target}"
                            ) from exc

                if action == "hover":
                    locator = await _locator_for_pointer_target()
                    if locator is None:
                        raise HTTPException(status_code=400, detail="selector or text is required")
                    try:
                        await locator.wait_for(state="visible", timeout=timeout_ms)
                    except PlaywrightTimeoutError:
                        pass
                    try:
                        await locator.scroll_into_view_if_needed(timeout=timeout_ms)
                    except PlaywrightTimeoutError:
                        pass
                    await locator.hover(timeout=timeout_ms, force=True)
                    return {"status": "ok"}

                if action == "move_mouse":
                    move_x, move_y = await _pointer_xy_from_payload_or_target()
                    await page.mouse.move(move_x, move_y, steps=mouse_steps)
                    return {"status": "ok", "x": move_x, "y": move_y}

                if action == "click_at":
                    click_x, click_y = await _pointer_xy_from_payload_or_target()
                    await page.mouse.move(click_x, click_y, steps=mouse_steps)
                    await page.mouse.click(click_x, click_y, button=button, click_count=max(1, click_count))
                    return {"status": "ok", "x": click_x, "y": click_y}

                if action in {"type", "fill"}:
                    if not selector:
                        raise HTTPException(status_code=400, detail="selector is required")
                    locator = page.locator(selector).first
                    if action == "fill":
                        await locator.fill(text, timeout=timeout_ms)
                    else:
                        await locator.type(text, timeout=timeout_ms)
                    return {"status": "ok"}

                if action == "fill_form":
                    fields = req.payload.get("fields")
                    if not fields:
                        raise HTTPException(status_code=400, detail="fields is required")
                    last_locator = None
                    for field in fields:
                        sel = field.get("selector")
                        val = field.get("value", "")
                        mode = field.get("mode", "fill")
                        if not sel:
                            continue
                        locator = page.locator(sel).first
                        last_locator = locator
                        if mode == "type":
                            await locator.type(val, timeout=timeout_ms)
                        else:
                            await locator.fill(val, timeout=timeout_ms)
                    submit_selector = req.payload.get("submit_selector")
                    if submit_selector:
                        await page.locator(submit_selector).first.click(timeout=timeout_ms)
                    elif req.payload.get("submit") and last_locator is not None:
                        await last_locator.press("Enter", timeout=timeout_ms)
                    wait_for = req.payload.get("wait_for")
                    if wait_for:
                        await page.wait_for_selector(wait_for, timeout=timeout_ms)
                    return {"status": "ok"}

                if action == "login":
                    username = req.payload.get("username")
                    password = req.payload.get("password")
                    if not username or not password:
                        raise HTTPException(status_code=400, detail="username and password are required")
                    user_sel = req.payload.get("username_selector")
                    pass_sel = req.payload.get("password_selector")
                    submit_selector = req.payload.get("submit_selector")
                    if user_sel:
                        user_locator = page.locator(user_sel).first
                    else:
                        user_locator = page.locator(
                            'input[type="email"], input[name*="email" i], input[autocomplete="username"], input[type="text"]'
                        ).first
                    if pass_sel:
                        pass_locator = page.locator(pass_sel).first
                    else:
                        pass_locator = page.locator('input[type="password"]').first
                    await user_locator.fill(username, timeout=timeout_ms)
                    await pass_locator.fill(password, timeout=timeout_ms)
                    if submit_selector:
                        await page.locator(submit_selector).first.click(timeout=timeout_ms)
                    else:
                        await pass_locator.press("Enter", timeout=timeout_ms)
                    wait_for = req.payload.get("wait_for")
                    if wait_for:
                        await page.wait_for_selector(wait_for, timeout=timeout_ms)
                    return {"status": "ok"}

                if action == "press":
                    key = req.payload.get("key")
                    if not key:
                        raise HTTPException(status_code=400, detail="key is required")
                    if selector:
                        await page.locator(selector).first.press(key, timeout=timeout_ms)
                    else:
                        await page.keyboard.press(key)
                    return {"status": "ok"}

                if action == "wait":
                    if selector:
                        await page.wait_for_selector(selector, timeout=timeout_ms)
                    else:
                        await asyncio.sleep(min(timeout_ms / 1000.0, 30.0))
                    return {"status": "ok"}

                if action == "snapshot":
                    mode = req.payload.get("mode", "text")
                    html = await page.content()
                    response: dict[str, Any] = {"status": "ok"}
                    if mode == "html":
                        response["content"] = html[:max_chars]
                    else:
                        text_content = await page.inner_text("body")
                        response["content"] = text_content[:max_chars]
                    if include_elements:
                        elements = await page.evaluate(
                            """
                            () => {
                              const max = 200;
                              const candidates = Array.from(
                                document.querySelectorAll('a, button, input, select, textarea, [role]')
                              ).slice(0, max);
                              const uniqueSelector = (el) => {
                                if (el.id) return `#${el.id}`;
                                const dataTest = el.getAttribute('data-testid');
                                if (dataTest) return `[data-testid="${dataTest}"]`;
                                const aria = el.getAttribute('aria-label');
                                if (aria) return `[aria-label="${aria}"]`;
                                let path = el.tagName.toLowerCase();
                                let parent = el.parentElement;
                                while (parent && parent.tagName.toLowerCase() !== 'body') {
                                  const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                                  if (siblings.length > 1) {
                                    const index = siblings.indexOf(el) + 1;
                                    path = `${parent.tagName.toLowerCase()}:nth-child(${index}) > ${path}`;
                                  } else {
                                    path = `${parent.tagName.toLowerCase()} > ${path}`;
                                  }
                                  el = parent;
                                  parent = parent.parentElement;
                                }
                                return path;
                              };
                              return candidates.map(el => {
                                const rect = el.getBoundingClientRect();
                                return {
                                  selector: uniqueSelector(el),
                                  tag: el.tagName.toLowerCase(),
                                  text: (el.innerText || el.value || '').trim().slice(0, 120),
                                  role: el.getAttribute('role') || null,
                                  href: el.getAttribute('href') || null,
                                  x: Math.round(rect.x),
                                  y: Math.round(rect.y),
                                  width: Math.round(rect.width),
                                  height: Math.round(rect.height),
                                };
                              });
                            }
                            """
                        )
                        response["elements"] = elements[: max_elements]
                    return response

                if action == "evaluate":
                    if not script or not str(script).strip():
                        raise HTTPException(status_code=400, detail="script is required")
                    try:
                        value = await page.evaluate(str(script), eval_arg)
                    except PlaywrightTimeoutError as exc:
                        raise HTTPException(status_code=400, detail="Timeout evaluating script") from exc
                    except Exception as exc:
                        raise HTTPException(status_code=400, detail=f"Evaluate failed: {exc}") from exc
                    try:
                        # Ensure response is JSON-serializable for transport.
                        json.dumps(value)
                        serializable_value: Any = value
                    except TypeError:
                        serializable_value = str(value)
                    return {"status": "ok", "result": serializable_value}

                if action == "screenshot":
                    if selector:
                        locator = page.locator(selector).first
                        try:
                            await locator.wait_for(state="visible", timeout=timeout_ms)
                            png = await locator.screenshot(timeout=timeout_ms)
                        except PlaywrightTimeoutError as exc:
                            raise HTTPException(status_code=400, detail=f"Timeout waiting for selector: {selector}") from exc
                    else:
                        png = await _capture_page_screenshot(page, full_page=full_page, timeout_ms=timeout_ms)
                    screenshot_path = _save_screenshot(workspace_root, session_id, png)
                    return {"status": "ok", "screenshot_path": screenshot_path}

                if action == "close":
                    ctx = _contexts.pop(profile_id, None)
                    _pages.pop(profile_id, None)
                    if ctx is not None:
                        await ctx.close()
                    return {"status": "ok"}

                if action == "status":
                    return {
                        "status": "ok",
                        "active": profile_id in _contexts,
                        "url": page.url if profile_id in _pages else None,
                    }

                raise HTTPException(status_code=400, detail="Unknown browser_action")

        raise HTTPException(status_code=400, detail="Unknown tool")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/tasks/status")
    async def tasks_status(req: TaskStatusRequest):
        running = []
        for pid in req.pids:
            try:
                os.kill(int(pid), 0)
                running.append(int(pid))
            except OSError:
                continue
        return {"status": "ok", "running": running}

    @app.get("/processes/active")
    async def processes_active():
        processes = _list_non_runner_processes()
        return {"status": "ok", "active": bool(processes), "count": len(processes), "processes": processes}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=9080)
