from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import base64
from typing import Any, Dict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from datetime import datetime


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


def _get_lock(session_id: str) -> asyncio.Lock:
    lock = _locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[session_id] = lock
    return lock


def _safe_session(session_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id)


def _save_screenshot(workspace_root: Path, session_id: str, png: bytes) -> str:
    shots_root = workspace_root / "screenshots" / _safe_session(session_id)
    shots_root.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.png"
    path = shots_root / filename
    path.write_bytes(png)
    return str(Path("screenshots") / _safe_session(session_id) / filename)


def _clear_browser_locks(data_dir: Path) -> None:
    # Clear Chromium profile locks that can remain after a crash/restart.
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            lock_path = data_dir / name
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            continue


def _clear_all_browser_locks(browser_data_root: Path) -> None:
    if not browser_data_root.exists():
        return
    for child in browser_data_root.iterdir():
        if child.is_dir():
            _clear_browser_locks(child)


async def _get_context(
    session_id: str, browser_data_root: Path, width: int, height: int, executable: str | None
) -> BrowserContext:
    global _playwright
    if _playwright is None:
        _playwright = await async_playwright().start()
    if session_id in _contexts:
        return _contexts[session_id]
    data_dir = browser_data_root / _safe_session(session_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=str(data_dir),
        viewport={"width": width, "height": height},
        executable_path=executable,
        args=["--disable-dev-shm-usage"],
    )
    _contexts[session_id] = context
    return context


async def _get_page(session_id: str, context: BrowserContext) -> Page:
    if session_id in _pages:
        return _pages[session_id]
    pages = context.pages
    page = pages[0] if pages else await context.new_page()
    _pages[session_id] = page
    return page


def create_app() -> FastAPI:
    workspace_root = Path(os.environ.get("SKITTER_WORKSPACE_ROOT", "/tmp/skitter-workspace"))
    workspace_root.mkdir(parents=True, exist_ok=True)
    browser_data_root = Path(os.environ.get("SKITTER_BROWSER_DATA_ROOT", "/browser-data"))
    browser_data_root.mkdir(parents=True, exist_ok=True)
    browser_executable = os.environ.get("SKITTER_BROWSER_EXECUTABLE") or None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _clear_all_browser_locks(browser_data_root)
        yield

    app = FastAPI(title="Skittermander Sandbox", lifespan=lifespan)

    def safe_path(path: str) -> Path:
        raw = Path(path)
        if raw.is_absolute():
            try:
                candidate = raw.resolve()
                if workspace_root in candidate.parents or candidate == workspace_root:
                    return candidate
            except OSError:
                pass
            # Treat absolute paths as workspace-relative (strip leading slash)
            raw = Path(str(raw).lstrip("/"))
        candidate = (workspace_root / raw).resolve()
        if workspace_root not in candidate.parents and candidate != workspace_root:
            raise HTTPException(status_code=400, detail="Invalid path")
        return candidate

    def _payload_path(payload: Dict[str, Any]) -> str:
        return payload.get("path") or payload.get("file_path") or ""

    def _workspace_response_path(target: Path) -> str:
        try:
            rel = target.relative_to(workspace_root)
        except ValueError:
            rel = target.name
        return str(Path("/workspace") / rel)

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

    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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
                ext = target.suffix.lower()
                if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    content_type = "image/jpeg" if ext in {".jpg", ".jpeg"} else f"image/{ext.lstrip('.')}"
                    return {
                        "status": "ok",
                        "file_path": _workspace_response_path(target),
                        "content_type": content_type,
                    }
                offset = _coerce_int(req.payload.get("offset"))
                limit = _coerce_int(req.payload.get("limit"))
                return _read_text_file(target, offset=offset, limit=limit)
            if req.tool == "write":
                content = req.payload.get("content")
                if content is None:
                    raise HTTPException(status_code=400, detail="content is required")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
                return {"status": "ok"}
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
                return {"status": "ok", "entries": [p.name for p in target.iterdir()]}
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

        if req.tool == "http_fetch":
            url = req.payload.get("url")
            if not url:
                raise HTTPException(status_code=400, detail="url is required")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                return {"status": "ok", "status_code": resp.status_code, "body": resp.text[:10000]}

        if req.tool == "shell":
            cmd = req.payload.get("cmd")
            args = req.payload.get("args")
            cwd = req.payload.get("cwd", "")
            background = bool(req.payload.get("background", False))
            log_path = req.payload.get("log_path")
            if not cmd and not args:
                raise HTTPException(status_code=400, detail="cmd or args is required")
            working_dir = safe_path(cwd) if cwd else workspace_root

            if args:
                argv = [str(arg) for arg in args]
            else:
                argv = ["/bin/sh", "-lc", str(cmd)]

            try:
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

            def _trim(data: bytes) -> str:
                text = data.decode("utf-8", errors="replace")
                return text[:10000]

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
            data_dir = browser_data_root / _safe_session(req.session_id)
            data_dir.mkdir(parents=True, exist_ok=True)
            _clear_browser_locks(data_dir)
            async with async_playwright() as p:
                browser = await p.chromium.launch(executable_path=browser_executable, args=["--disable-dev-shm-usage"])
                context = await browser.new_context(viewport={"width": width, "height": height})
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                    title = await page.title()
                    html = await page.content()
                    html = html[:max_chars]
                    screenshot_path = None
                    if take_screenshot:
                        screenshot_path = _save_screenshot(
                            workspace_root, req.session_id, await page.screenshot(full_page=True)
                        )
                    return {"status": "ok", "title": title, "html": html, "screenshot_path": screenshot_path}
                except PlaywrightTimeoutError:
                    return {"status": "timeout", "detail": f"Timeout navigating to {url}"}
                finally:
                    await browser.close()

        if req.tool == "browser_action":
            action = req.payload.get("action")
            session_id = req.session_id
            if not action:
                raise HTTPException(status_code=400, detail="action is required")

            width = int(req.payload.get("width", 1920))
            height = int(req.payload.get("height", 1080))
            selector = req.payload.get("selector")
            url = req.payload.get("url")
            text = req.payload.get("text", "")
            timeout_ms = int(req.payload.get("timeout_ms", 30000))
            wait_until = req.payload.get("wait_until", "domcontentloaded")
            full_page = bool(req.payload.get("full_page", True))
            max_chars = int(req.payload.get("max_chars", 20000))
            include_elements = bool(req.payload.get("include_elements", False))
            max_elements = int(req.payload.get("max_elements", 50))

            async with _get_lock(session_id):
                context = await _get_context(session_id, browser_data_root, width, height, browser_executable)
                page = await _get_page(session_id, context)
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
                    _pages[session_id] = tab
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
                    _pages[session_id] = pages[0] if pages else await context.new_page()
                    return {"status": "ok"}

                if action == "click":
                    if not selector:
                        raise HTTPException(status_code=400, detail="selector is required")
                    await page.locator(selector).first.click(timeout=timeout_ms)
                    return {"status": "ok"}

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

                if action == "screenshot":
                    if selector:
                        locator = page.locator(selector).first
                        try:
                            await locator.wait_for(state="visible", timeout=timeout_ms)
                            png = await locator.screenshot(timeout=timeout_ms)
                        except PlaywrightTimeoutError as exc:
                            raise HTTPException(status_code=400, detail=f"Timeout waiting for selector: {selector}") from exc
                    else:
                        png = await page.screenshot(full_page=full_page)
                    screenshot_path = _save_screenshot(workspace_root, session_id, png)
                    return {"status": "ok", "screenshot_path": screenshot_path}

                if action == "close":
                    ctx = _contexts.pop(session_id, None)
                    _pages.pop(session_id, None)
                    if ctx is not None:
                        await ctx.close()
                    return {"status": "ok"}

                if action == "status":
                    return {
                        "status": "ok",
                        "active": session_id in _contexts,
                        "url": page.url if session_id in _pages else None,
                    }

                raise HTTPException(status_code=400, detail="Unknown browser_action")

        if req.tool == "sub_agent":
            return {"status": "pending", "detail": "Sub-agent tool is handled by the main runtime"}

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

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=9080)
