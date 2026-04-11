from __future__ import annotations

import asyncio
import base64
import ctypes
import ctypes.util
import locale
import json
import mimetypes
import os
import shutil
import sys
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel

try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover - optional on some Pillow builds
    ImageGrab = None

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
_application_services = None


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


_KCG_HID_EVENT_TAP = 0
_KCG_EVENT_LEFT_MOUSE_DOWN = 1
_KCG_EVENT_LEFT_MOUSE_UP = 2
_KCG_EVENT_RIGHT_MOUSE_DOWN = 3
_KCG_EVENT_RIGHT_MOUSE_UP = 4
_KCG_EVENT_MOUSE_MOVED = 5
_KCG_EVENT_KEY_DOWN = 10
_KCG_EVENT_KEY_UP = 11

_KCG_MOUSE_BUTTON_LEFT = 0
_KCG_MOUSE_BUTTON_RIGHT = 1
_KCG_MOUSE_BUTTON_CENTER = 2

_CG_FLAG_MASK_SHIFT = 1 << 17
_CG_FLAG_MASK_CONTROL = 1 << 18
_CG_FLAG_MASK_OPTION = 1 << 19
_CG_FLAG_MASK_COMMAND = 1 << 20
_CG_FLAG_MASK_FUNCTION = 1 << 23

_MAC_KEYCODES: dict[str, int] = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "enter": 36,
    "return": 36,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
    "tab": 48,
    "space": 49,
    "`": 50,
    "backspace": 51,
    "delete": 51,
    "escape": 53,
    "esc": 53,
    "command": 55,
    "cmd": 55,
    "shift": 56,
    "caps_lock": 57,
    "capslock": 57,
    "option": 58,
    "alt": 58,
    "control": 59,
    "ctrl": 59,
    "right_shift": 60,
    "right_option": 61,
    "right_alt": 61,
    "right_control": 62,
    "fn": 63,
    "function": 63,
    "f17": 64,
    "volume_up": 72,
    "volume_down": 73,
    "mute": 74,
    "f18": 79,
    "f19": 80,
    "f20": 90,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f3": 99,
    "f8": 100,
    "f9": 101,
    "f11": 103,
    "f13": 105,
    "f16": 106,
    "f14": 107,
    "f10": 109,
    "f12": 111,
    "f15": 113,
    "help": 114,
    "home": 115,
    "page_up": 116,
    "pageup": 116,
    "forward_delete": 117,
    "delete_forward": 117,
    "f4": 118,
    "end": 119,
    "f2": 120,
    "page_down": 121,
    "pagedown": 121,
    "f1": 122,
    "left": 123,
    "arrowleft": 123,
    "right": 124,
    "arrowright": 124,
    "down": 125,
    "arrowdown": 125,
    "up": 126,
    "arrowup": 126,
}

_MAC_MODIFIER_FLAGS: dict[str, int] = {
    "shift": _CG_FLAG_MASK_SHIFT,
    "control": _CG_FLAG_MASK_CONTROL,
    "ctrl": _CG_FLAG_MASK_CONTROL,
    "option": _CG_FLAG_MASK_OPTION,
    "alt": _CG_FLAG_MASK_OPTION,
    "command": _CG_FLAG_MASK_COMMAND,
    "cmd": _CG_FLAG_MASK_COMMAND,
    "function": _CG_FLAG_MASK_FUNCTION,
    "fn": _CG_FLAG_MASK_FUNCTION,
}

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1

_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

_VK_BACK = 0x08
_VK_TAB = 0x09
_VK_RETURN = 0x0D
_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_ESCAPE = 0x1B
_VK_SPACE = 0x20
_VK_PRIOR = 0x21
_VK_NEXT = 0x22
_VK_END = 0x23
_VK_HOME = 0x24
_VK_LEFT = 0x25
_VK_UP = 0x26
_VK_RIGHT = 0x27
_VK_DOWN = 0x28
_VK_DELETE = 0x2E
_VK_LWIN = 0x5B

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


_WIN_KEYCODES: dict[str, int] = {
    "enter": _VK_RETURN,
    "return": _VK_RETURN,
    "tab": _VK_TAB,
    "space": _VK_SPACE,
    "escape": _VK_ESCAPE,
    "esc": _VK_ESCAPE,
    "backspace": _VK_BACK,
    "delete": _VK_DELETE,
    "left": _VK_LEFT,
    "arrowleft": _VK_LEFT,
    "up": _VK_UP,
    "arrowup": _VK_UP,
    "right": _VK_RIGHT,
    "arrowright": _VK_RIGHT,
    "down": _VK_DOWN,
    "arrowdown": _VK_DOWN,
    "home": _VK_HOME,
    "end": _VK_END,
    "page_up": _VK_PRIOR,
    "pageup": _VK_PRIOR,
    "page_down": _VK_NEXT,
    "pagedown": _VK_NEXT,
}
for _idx in range(1, 25):
    _WIN_KEYCODES[f"f{_idx}"] = 0x70 + _idx - 1

_WIN_MODIFIER_KEYCODES: dict[str, int] = {
    "shift": _VK_SHIFT,
    "control": _VK_CONTROL,
    "ctrl": _VK_CONTROL,
    "alt": _VK_MENU,
    "option": _VK_MENU,
    "cmd": _VK_LWIN,
    "command": _VK_LWIN,
    "win": _VK_LWIN,
    "windows": _VK_LWIN,
}

_user32: Any | None = None


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
    filename = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}.png"
    path = shots_root / filename
    path.write_bytes(png)
    return str(Path("screenshots") / _safe_session(session_id) / filename)


def _new_screenshot_target(workspace_root: Path, session_id: str) -> Path:
    shots_root = workspace_root / "screenshots" / _safe_session(session_id)
    shots_root.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}.png"
    return shots_root / filename


def _image_pixel_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            return int(width), int(height)
    except OSError:
        return None
    return None


def _decode_process_output(data: bytes) -> str:
    encoding = locale.getpreferredencoding(False) or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")


def _powershell_argv(command: str) -> list[str]:
    executable = _powershell_executable()
    if not executable:
        raise HTTPException(status_code=503, detail="PowerShell is not available on this executor")
    return [
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]


def _shell_argv_for_command(command: str) -> list[str]:
    if sys.platform == "win32":
        return _powershell_argv(command)
    shell_path = "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"
    return [shell_path, "-lc", command]


def _powershell_single_quoted(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _clean_patch_header_path(value: str) -> str:
    path = str(value or "").strip().split("\t", 1)[0].strip()
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        path = path[1:-1]
    return path


def _detect_patch_strip_count(patch_text: str) -> int:
    for raw_line in patch_text.splitlines():
        if raw_line.startswith("--- ") or raw_line.startswith("+++ "):
            candidate = _clean_patch_header_path(raw_line[4:])
            if not candidate or candidate == "/dev/null":
                continue
            if candidate.startswith(("a/", "b/")):
                return 1
            return 0
    return 0


def _strip_patch_path(path: str, strip_count: int) -> str:
    cleaned = _clean_patch_header_path(path)
    if cleaned in {"", "/dev/null"}:
        return cleaned
    if strip_count <= 0:
        return cleaned
    prefix = ""
    remainder = cleaned
    if remainder.startswith("/"):
        prefix = "/"
        remainder = remainder.lstrip("/")
    parts = [part for part in remainder.replace("\\", "/").split("/") if part]
    stripped = "/".join(parts[strip_count:])
    return f"{prefix}{stripped}" if prefix else stripped


def _patch_target_path(working_dir: Path, old_path: str, new_path: str, strip_count: int) -> Path:
    preferred = new_path if _clean_patch_header_path(new_path) != "/dev/null" else old_path
    stripped = _strip_patch_path(preferred, strip_count)
    if not stripped or stripped == "/dev/null":
        raise ValueError("patch target path is missing")
    target = Path(stripped)
    if target.is_absolute():
        return target
    return working_dir / target


def _parse_hunk_header(line: str) -> int:
    marker = line.split(" ", 2)[1]
    old_range = marker[1:]
    start_text = old_range.split(",", 1)[0]
    return int(start_text)


def _consume_patch_line(original: list[str], index: int, expected: str, target: Path) -> str:
    if index >= len(original):
        raise ValueError(f"patch context did not match {target}: reached end of file")
    actual = original[index]
    if actual != expected and actual.rstrip("\r\n") != expected.rstrip("\r\n"):
        raise ValueError(f"patch context did not match {target}")
    return actual


def _apply_single_file_patch(target: Path, hunks: list[tuple[int, list[str]]], *, delete_file: bool) -> None:
    original = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if target.exists() else []
    output: list[str] = []
    source_index = 0
    for old_start, hunk_lines in hunks:
        hunk_start = max(0, old_start - 1)
        if hunk_start < source_index:
            raise ValueError(f"overlapping patch hunks for {target}")
        output.extend(original[source_index:hunk_start])
        source_index = hunk_start
        for raw in hunk_lines:
            if not raw:
                continue
            marker = raw[0]
            content = raw[1:]
            if marker == " ":
                output.append(_consume_patch_line(original, source_index, content, target))
                source_index += 1
            elif marker == "-":
                _consume_patch_line(original, source_index, content, target)
                source_index += 1
            elif marker == "+":
                output.append(content)
            elif marker == "\\":
                continue
            else:
                raise ValueError(f"unsupported patch line for {target}: {raw[:40]}")
    output.extend(original[source_index:])
    if delete_file:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(output), encoding="utf-8")


def _apply_unified_patch_fallback(patch_text: str, working_dir: Path, strip_count: int) -> str:
    lines = str(patch_text).splitlines(keepends=True)
    index = 0
    patched: list[str] = []
    while index < len(lines):
        line = lines[index]
        if not line.startswith("--- "):
            index += 1
            continue
        old_path = line[4:].rstrip("\r\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ValueError("malformed patch: expected +++ header")
        new_path = lines[index][4:].rstrip("\r\n")
        index += 1
        target = _patch_target_path(working_dir, old_path, new_path, strip_count)
        delete_file = _clean_patch_header_path(new_path) == "/dev/null"
        hunks: list[tuple[int, list[str]]] = []
        while index < len(lines):
            current = lines[index]
            if current.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
                break
            if not current.startswith("@@ "):
                index += 1
                continue
            old_start = _parse_hunk_header(current)
            index += 1
            hunk_lines: list[str] = []
            while index < len(lines):
                current = lines[index]
                if current.startswith("@@ ") or (
                    current.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ ")
                ):
                    break
                if current[:1] in {" ", "-", "+", "\\"}:
                    hunk_lines.append(current)
                index += 1
            hunks.append((old_start, hunk_lines))
        if not hunks:
            raise ValueError(f"patch for {target} did not contain any hunks")
        _apply_single_file_patch(target, hunks, delete_file=delete_file)
        patched.append(str(target.relative_to(working_dir) if target.is_relative_to(working_dir) else target))
    if not patched:
        raise ValueError("patch did not contain any file changes")
    return "".join(f"patching file {path}\n" for path in patched)


async def _execute_apply_patch(patch_text: str, working_dir: Path, strip_count: int) -> dict[str, Any]:
    use_fallback = sys.platform == "win32" or shutil.which("patch") is None
    if use_fallback:
        try:
            stdout = await asyncio.to_thread(_apply_unified_patch_fallback, patch_text, working_dir, strip_count)
        except Exception as exc:
            return {"status": "error", "exit_code": 1, "stdout": "", "stderr": str(exc), "strip": strip_count}
        return {"status": "ok", "exit_code": 0, "stdout": stdout, "stderr": "", "strip": strip_count}

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
    except FileNotFoundError:
        try:
            stdout = await asyncio.to_thread(_apply_unified_patch_fallback, patch_text, working_dir, strip_count)
        except Exception as exc:
            return {"status": "error", "exit_code": 1, "stdout": "", "stderr": str(exc), "strip": strip_count}
        return {"status": "ok", "exit_code": 0, "stdout": stdout, "stderr": "", "strip": strip_count}
    stdout, stderr = await proc.communicate(str(patch_text).encode("utf-8"))
    return {
        "status": "ok" if proc.returncode == 0 else "error",
        "exit_code": proc.returncode,
        "stdout": _decode_process_output(stdout)[:12000],
        "stderr": _decode_process_output(stderr)[:12000],
        "strip": strip_count,
    }


async def _run_host_command(*argv: str, timeout_seconds: float = 15.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"{argv[0]} is not available on this executor") from exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        proc.kill()
        raise HTTPException(status_code=504, detail=f"{argv[0]} timed out on this executor") from exc
    return proc.returncode, _decode_process_output(stdout), _decode_process_output(stderr)


def _load_application_services():
    global _application_services
    if _application_services is not None:
        return _application_services
    library_path = ctypes.util.find_library("ApplicationServices")
    if not library_path:
        raise HTTPException(status_code=503, detail="ApplicationServices framework is not available on this executor")
    lib = ctypes.cdll.LoadLibrary(library_path)
    lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    lib.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    lib.CGEventCreate.restype = ctypes.c_void_p
    lib.CGEventCreate.argtypes = [ctypes.c_void_p]
    lib.CGEventGetLocation.restype = CGPoint
    lib.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    lib.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    lib.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    lib.CGEventKeyboardSetUnicodeString.restype = None
    lib.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
    lib.CGEventSetFlags.restype = None
    lib.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.CGEventPost.restype = None
    lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    lib.CGWarpMouseCursorPosition.restype = ctypes.c_int32
    lib.CGWarpMouseCursorPosition.argtypes = [CGPoint]
    try:
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        lib.AXIsProcessTrusted.argtypes = []
    except AttributeError:
        pass
    try:
        core_foundation_path = ctypes.util.find_library("CoreFoundation")
        if core_foundation_path:
            core_foundation = ctypes.cdll.LoadLibrary(core_foundation_path)
            core_foundation.CFRelease.restype = None
            core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
            lib._CFRelease = core_foundation.CFRelease
        else:
            lib._CFRelease = None
    except Exception:
        lib._CFRelease = None
    _application_services = lib
    return lib


def _mac_require_accessibility() -> Any:
    lib = _load_application_services()
    checker = getattr(lib, "AXIsProcessTrusted", None)
    if checker is not None and not checker():
        raise HTTPException(
            status_code=503,
            detail=(
                "Accessibility permission is required on this executor for mouse/keyboard control. "
                "Enable it in System Settings > Privacy & Security > Accessibility."
            ),
        )
    return lib


def _mac_release(lib: Any, ref: int | None) -> None:
    if not ref:
        return
    releaser = getattr(lib, "_CFRelease", None)
    if releaser is not None:
        releaser(ref)


def _mac_cursor_position() -> tuple[int, int] | None:
    lib = _load_application_services()
    event_ref = lib.CGEventCreate(None)
    if not event_ref:
        return None
    try:
        point = lib.CGEventGetLocation(event_ref)
        return int(round(point.x)), int(round(point.y))
    finally:
        _mac_release(lib, event_ref)


def _mac_mouse_button(button: str) -> tuple[int, int, int]:
    normalized = str(button or "left").strip().lower()
    if normalized == "left":
        return _KCG_MOUSE_BUTTON_LEFT, _KCG_EVENT_LEFT_MOUSE_DOWN, _KCG_EVENT_LEFT_MOUSE_UP
    if normalized == "right":
        return _KCG_MOUSE_BUTTON_RIGHT, _KCG_EVENT_RIGHT_MOUSE_DOWN, _KCG_EVENT_RIGHT_MOUSE_UP
    raise HTTPException(status_code=400, detail="button must be left or right")


def _mac_modifier_flags(modifiers: list[str] | None) -> int:
    flags = 0
    for modifier in modifiers or []:
        normalized = str(modifier or "").strip().lower()
        if not normalized:
            continue
        flag = _MAC_MODIFIER_FLAGS.get(normalized)
        if flag is None:
            raise HTTPException(status_code=400, detail=f"Unsupported modifier: {modifier}")
        flags |= flag
    return flags


def _mac_mouse_move_sync(x: float, y: float) -> dict[str, Any]:
    lib = _mac_require_accessibility()
    point = CGPoint(float(x), float(y))
    event_ref = lib.CGEventCreateMouseEvent(None, _KCG_EVENT_MOUSE_MOVED, point, _KCG_MOUSE_BUTTON_LEFT)
    try:
        lib.CGWarpMouseCursorPosition(point)
        lib.CGEventPost(_KCG_HID_EVENT_TAP, event_ref)
    finally:
        _mac_release(lib, event_ref)
    return {"status": "ok", "x": float(x), "y": float(y)}


def _mac_mouse_click_sync(x: float, y: float, button: str, click_count: int) -> dict[str, Any]:
    lib = _mac_require_accessibility()
    button_code, down_type, up_type = _mac_mouse_button(button)
    point = CGPoint(float(x), float(y))
    lib.CGWarpMouseCursorPosition(point)
    for _ in range(max(1, int(click_count))):
        down_ref = lib.CGEventCreateMouseEvent(None, down_type, point, button_code)
        up_ref = lib.CGEventCreateMouseEvent(None, up_type, point, button_code)
        try:
            lib.CGEventPost(_KCG_HID_EVENT_TAP, down_ref)
            lib.CGEventPost(_KCG_HID_EVENT_TAP, up_ref)
        finally:
            _mac_release(lib, down_ref)
            _mac_release(lib, up_ref)
        time.sleep(0.03)
    return {
        "status": "ok",
        "x": float(x),
        "y": float(y),
        "button": button,
        "click_count": max(1, int(click_count)),
    }


def _mac_keyboard_type_sync(text: str) -> dict[str, Any]:
    lib = _mac_require_accessibility()
    content = str(text or "")
    if not content:
        raise HTTPException(status_code=400, detail="text is required")
    for char in content:
        chars = (ctypes.c_uint16 * 1)(ord(char))
        down_ref = lib.CGEventCreateKeyboardEvent(None, 0, True)
        up_ref = lib.CGEventCreateKeyboardEvent(None, 0, False)
        try:
            lib.CGEventKeyboardSetUnicodeString(down_ref, 1, chars)
            lib.CGEventKeyboardSetUnicodeString(up_ref, 1, chars)
            lib.CGEventPost(_KCG_HID_EVENT_TAP, down_ref)
            lib.CGEventPost(_KCG_HID_EVENT_TAP, up_ref)
        finally:
            _mac_release(lib, down_ref)
            _mac_release(lib, up_ref)
        time.sleep(0.01)
    return {"status": "ok", "text": content, "chars": len(content)}


def _mac_keyboard_press_sync(key: str, modifiers: list[str] | None) -> dict[str, Any]:
    lib = _mac_require_accessibility()
    normalized = str(key or "").strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="key is required")
    keycode = _MAC_KEYCODES.get(normalized)
    if keycode is None:
        raise HTTPException(status_code=400, detail=f"Unsupported key: {key}")
    flags = _mac_modifier_flags(modifiers)
    down_ref = lib.CGEventCreateKeyboardEvent(None, keycode, True)
    up_ref = lib.CGEventCreateKeyboardEvent(None, keycode, False)
    try:
        if flags:
            lib.CGEventSetFlags(down_ref, flags)
            lib.CGEventSetFlags(up_ref, flags)
        lib.CGEventPost(_KCG_HID_EVENT_TAP, down_ref)
        lib.CGEventPost(_KCG_HID_EVENT_TAP, up_ref)
    finally:
        _mac_release(lib, down_ref)
        _mac_release(lib, up_ref)
    return {"status": "ok", "key": normalized, "modifiers": list(modifiers or [])}


def _load_user32() -> Any:
    if sys.platform != "win32":
        raise HTTPException(status_code=503, detail="Windows desktop control is only available on Windows nodes")
    global _user32
    if _user32 is not None:
        return _user32
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise HTTPException(status_code=503, detail="Win32 user32 APIs are not available on this executor")
    user32 = windll.user32
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = ctypes.c_bool
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = ctypes.c_bool
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    _user32 = user32
    return user32


def _win_cursor_position() -> tuple[int, int] | None:
    try:
        user32 = _load_user32()
        point = POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)
    except HTTPException:
        return None


def _win_keyboard_input(*, vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(
        type=_INPUT_KEYBOARD,
        union=INPUT_UNION(
            ki=KEYBDINPUT(
                wVk=vk,
                wScan=scan,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )


def _win_mouse_input(flags: int) -> INPUT:
    return INPUT(
        type=_INPUT_MOUSE,
        union=INPUT_UNION(
            mi=MOUSEINPUT(
                dx=0,
                dy=0,
                mouseData=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )


def _win_send_inputs(inputs: list[INPUT]) -> None:
    user32 = _load_user32()
    input_array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), input_array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise HTTPException(status_code=503, detail="Windows SendInput failed on this executor")


def _win_key_down(vk: int) -> INPUT:
    return _win_keyboard_input(vk=vk)


def _win_key_up(vk: int) -> INPUT:
    return _win_keyboard_input(vk=vk, flags=_KEYEVENTF_KEYUP)


def _win_mouse_button(button: str) -> tuple[int, int]:
    normalized = str(button or "left").strip().lower()
    if normalized == "left":
        return _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
    if normalized == "right":
        return _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
    raise HTTPException(status_code=400, detail="button must be left or right")


def _win_mouse_move_sync(x: float, y: float) -> dict[str, Any]:
    user32 = _load_user32()
    target_x = int(round(float(x)))
    target_y = int(round(float(y)))
    if not user32.SetCursorPos(target_x, target_y):
        raise HTTPException(status_code=503, detail="Windows SetCursorPos failed on this executor")
    return {"status": "ok", "x": float(x), "y": float(y)}


def _win_mouse_click_sync(x: float, y: float, button: str, click_count: int) -> dict[str, Any]:
    _win_mouse_move_sync(x, y)
    down_flag, up_flag = _win_mouse_button(button)
    inputs: list[INPUT] = []
    for _ in range(max(1, int(click_count))):
        inputs.append(_win_mouse_input(down_flag))
        inputs.append(_win_mouse_input(up_flag))
    _win_send_inputs(inputs)
    return {
        "status": "ok",
        "x": float(x),
        "y": float(y),
        "button": str(button or "left"),
        "click_count": max(1, int(click_count)),
    }


def _win_keyboard_type_sync(text: str) -> dict[str, Any]:
    content = str(text or "")
    if not content:
        raise HTTPException(status_code=400, detail="text is required")
    inputs: list[INPUT] = []
    encoded = content.encode("utf-16-le")
    units = [int.from_bytes(encoded[idx : idx + 2], "little") for idx in range(0, len(encoded), 2)]
    for unit in units:
        inputs.append(_win_keyboard_input(scan=unit, flags=_KEYEVENTF_UNICODE))
        inputs.append(_win_keyboard_input(scan=unit, flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
    _win_send_inputs(inputs)
    return {"status": "ok", "text": content, "chars": len(content)}


def _win_keycode(key: str) -> int:
    normalized = str(key or "").strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="key is required")
    if len(normalized) == 1 and normalized.isalpha():
        return ord(normalized.upper())
    if len(normalized) == 1 and normalized.isdigit():
        return ord(normalized)
    keycode = _WIN_KEYCODES.get(normalized)
    if keycode is None:
        raise HTTPException(status_code=400, detail=f"Unsupported key: {key}")
    return keycode


def _win_modifier_keycodes(modifiers: list[str] | None) -> list[int]:
    keycodes: list[int] = []
    for modifier in modifiers or []:
        normalized = str(modifier or "").strip().lower()
        if not normalized:
            continue
        keycode = _WIN_MODIFIER_KEYCODES.get(normalized)
        if keycode is None:
            raise HTTPException(status_code=400, detail=f"Unsupported modifier: {modifier}")
        keycodes.append(keycode)
    return keycodes


def _win_keyboard_press_sync(key: str, modifiers: list[str] | None) -> dict[str, Any]:
    normalized = str(key or "").strip().lower()
    keycode = _win_keycode(normalized)
    modifier_keycodes = _win_modifier_keycodes(modifiers)
    inputs: list[INPUT] = []
    for modifier in modifier_keycodes:
        inputs.append(_win_key_down(modifier))
    inputs.append(_win_key_down(keycode))
    inputs.append(_win_key_up(keycode))
    for modifier in reversed(modifier_keycodes):
        inputs.append(_win_key_up(modifier))
    _win_send_inputs(inputs)
    return {"status": "ok", "key": normalized, "modifiers": list(modifiers or [])}


def _win_screenshot_sync(target: Path) -> tuple[int | None, int | None]:
    if ImageGrab is None:
        raise HTTPException(status_code=503, detail="Pillow ImageGrab is not available on this executor")
    image = ImageGrab.grab(all_screens=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    return int(image.size[0]), int(image.size[1])


async def _execute_notify(payload: Dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "Skitter").strip() or "Skitter"
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
        code, stdout, stderr = await _run_host_command("osascript", "-e", script, timeout_seconds=10.0)
    elif sys.platform == "win32":
        script = "\n".join(
            [
                "Add-Type -AssemblyName System.Windows.Forms",
                "Add-Type -AssemblyName System.Drawing",
                "$notify = New-Object System.Windows.Forms.NotifyIcon",
                "$notify.Icon = [System.Drawing.SystemIcons]::Information",
                f"$notify.BalloonTipTitle = {_powershell_single_quoted(title)}",
                f"$notify.BalloonTipText = {_powershell_single_quoted(message)}",
                "$notify.Visible = $true",
                "$notify.ShowBalloonTip(3500)",
                "Start-Sleep -Milliseconds 3800",
                "$notify.Dispose()",
            ]
        )
        code, stdout, stderr = await _run_host_command(*_powershell_argv(script), timeout_seconds=10.0)
    elif shutil.which("notify-send"):
        code, stdout, stderr = await _run_host_command("notify-send", title, message, timeout_seconds=10.0)
    else:
        raise HTTPException(status_code=503, detail="Host notifications are not supported on this executor")
    if code != 0:
        detail = (stderr or stdout or "notification command failed").strip()
        raise HTTPException(status_code=503, detail=detail)
    return {"status": "ok", "title": title, "message": message}


async def _execute_screenshot(workspace_root: Path, session_id: str, payload: Dict[str, Any]) -> dict[str, Any]:
    target = _new_screenshot_target(workspace_root, session_id)
    include_cursor = bool(payload.get("include_cursor", True))
    cursor_position: tuple[int, int] | None = None
    if sys.platform == "darwin":
        cursor_position = _mac_cursor_position()
    elif sys.platform == "win32":
        cursor_position = _win_cursor_position()
    if sys.platform == "darwin":
        argv = ["screencapture", "-x"]
        if include_cursor:
            argv.append("-C")
        argv.append(str(target))
        code, stdout, stderr = await _run_host_command(*argv, timeout_seconds=20.0)
    elif sys.platform == "win32":
        try:
            width_px, height_px = await asyncio.to_thread(_win_screenshot_sync, target)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Windows screenshot capture failed: {exc}") from exc
        code, stdout, stderr = 0, "", ""
    elif shutil.which("gnome-screenshot"):
        argv = ["gnome-screenshot", "-f", str(target)]
        if include_cursor:
            argv.insert(1, "-p")
        code, stdout, stderr = await _run_host_command(*argv, timeout_seconds=20.0)
    elif shutil.which("grim"):
        argv = ["grim"]
        if include_cursor:
            argv.append("-c")
        argv.append(str(target))
        code, stdout, stderr = await _run_host_command(*argv, timeout_seconds=20.0)
    elif shutil.which("scrot"):
        argv = ["scrot"]
        if include_cursor:
            argv.append("--pointer")
        argv.append(str(target))
        code, stdout, stderr = await _run_host_command(*argv, timeout_seconds=20.0)
    else:
        raise HTTPException(status_code=503, detail="Host screenshots are not supported on this executor")
    if code != 0:
        detail = (stderr or stdout or "screenshot command failed").strip()
        raise HTTPException(
            status_code=503,
            detail=(
                "Screenshot capture failed. On macOS, also make sure Screen Recording permission is enabled "
                f"for this executor process. Details: {detail}"
            ),
        )
    if not target.exists():
        raise HTTPException(status_code=500, detail="Screenshot command finished without creating an image")
    pixel_size = _image_pixel_size(target)
    width_px = width_px if sys.platform == "win32" else pixel_size[0] if pixel_size else None
    height_px = height_px if sys.platform == "win32" else pixel_size[1] if pixel_size else None
    cursor_x = cursor_position[0] if cursor_position else None
    cursor_y = cursor_position[1] if cursor_position else None
    return {
        "status": "ok",
        "screenshot_path": str(Path("screenshots") / _safe_session(session_id) / target.name),
        "content_type": "image/png",
        "include_cursor": include_cursor,
        "size": target.stat().st_size,
        "width_px": width_px,
        "height_px": height_px,
        "cursor_x": cursor_x,
        "cursor_y": cursor_y,
    }


async def _execute_mouse_move(payload: Dict[str, Any]) -> dict[str, Any]:
    if payload.get("x") is None or payload.get("y") is None:
        raise HTTPException(status_code=400, detail="x and y are required")
    if sys.platform == "win32":
        return await asyncio.to_thread(_win_mouse_move_sync, float(payload["x"]), float(payload["y"]))
    if sys.platform != "darwin":
        raise HTTPException(status_code=503, detail="Host mouse control is currently supported on macOS and Windows nodes only")
    return await asyncio.to_thread(_mac_mouse_move_sync, float(payload["x"]), float(payload["y"]))


async def _execute_mouse_click(payload: Dict[str, Any]) -> dict[str, Any]:
    if payload.get("x") is None or payload.get("y") is None:
        raise HTTPException(status_code=400, detail="x and y are required")
    button = str(payload.get("button") or "left")
    click_count = int(payload.get("click_count", 1))
    if sys.platform == "win32":
        return await asyncio.to_thread(
            _win_mouse_click_sync,
            float(payload["x"]),
            float(payload["y"]),
            button,
            click_count,
        )
    if sys.platform != "darwin":
        raise HTTPException(status_code=503, detail="Host mouse control is currently supported on macOS and Windows nodes only")
    return await asyncio.to_thread(
        _mac_mouse_click_sync,
        float(payload["x"]),
        float(payload["y"]),
        button,
        click_count,
    )


async def _execute_keyboard_type(payload: Dict[str, Any]) -> dict[str, Any]:
    if sys.platform == "win32":
        return await asyncio.to_thread(_win_keyboard_type_sync, str(payload.get("text") or ""))
    if sys.platform != "darwin":
        raise HTTPException(status_code=503, detail="Host keyboard control is currently supported on macOS and Windows nodes only")
    return await asyncio.to_thread(_mac_keyboard_type_sync, str(payload.get("text") or ""))


async def _execute_keyboard_press(payload: Dict[str, Any]) -> dict[str, Any]:
    raw_modifiers = payload.get("modifiers")
    modifiers = [str(item) for item in raw_modifiers] if isinstance(raw_modifiers, list) else []
    if sys.platform == "win32":
        return await asyncio.to_thread(_win_keyboard_press_sync, str(payload.get("key") or ""), modifiers)
    if sys.platform != "darwin":
        raise HTTPException(status_code=503, detail="Host keyboard control is currently supported on macOS and Windows nodes only")
    return await asyncio.to_thread(_mac_keyboard_press_sync, str(payload.get("key") or ""), modifiers)


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
            result = await _execute_apply_patch(str(patch_text), working_dir, strip_count)
            result["cwd"] = _workspace_response_path(working_dir)
            return result

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
                date_dir = datetime.now(UTC).strftime("%Y-%m-%d")
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

        if req.tool == "notify":
            return await _execute_notify(req.payload)

        if req.tool == "screenshot":
            return await _execute_screenshot(workspace_root, req.session_id, req.payload)

        if req.tool == "mouse_move":
            return await _execute_mouse_move(req.payload)

        if req.tool == "mouse_click":
            return await _execute_mouse_click(req.payload)

        if req.tool == "keyboard_type":
            return await _execute_keyboard_type(req.payload)

        if req.tool == "keyboard_press":
            return await _execute_keyboard_press(req.payload)

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
                argv = _shell_argv_for_command(str(cmd))

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
                text = _decode_process_output(data)
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
