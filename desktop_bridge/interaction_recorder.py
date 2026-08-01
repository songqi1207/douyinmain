"""Opt-in JianYing mouse interaction recorder for automation diagnostics."""

from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any


JIANYING_PROCESSES = {"jianyingpro.exe", "capcut.exe"}
STOP_KEY = "F8"
_STOP_VIRTUAL_KEY = 0x77
_LEFT_VIRTUAL_KEY = 0x01
_RIGHT_VIRTUAL_KEY = 0x02


def normalize_recorded_point(
    x: int,
    y: int,
    rect: tuple[int, int, int, int],
) -> dict[str, float | int]:
    """Represent a screen point as stable window-relative coordinates."""

    left, top, right, bottom = (int(value) for value in rect)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0 or not (left <= int(x) <= right and top <= int(y) <= bottom):
        raise ValueError("点击位置不在有效窗口内")
    return {
        "screen_x": int(x),
        "screen_y": int(y),
        "window_x": int(x) - left,
        "window_y": int(y) - top,
        "x_ratio": round((int(x) - left) / width, 6),
        "y_ratio": round((int(y) - top) / height, 6),
        "x_from_right_ratio": round((right - int(x)) / width, 6),
        "y_from_bottom_ratio": round((bottom - int(y)) / height, 6),
        "window_width": width,
        "window_height": height,
    }


def _set_dpi_awareness(user32: Any) -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def _process_basename(window_handle: int) -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window_handle, ctypes.byref(process_id))
    handle = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).casefold()
    finally:
        kernel32.CloseHandle(handle)


def _window_text(user32: Any, window_handle: int) -> str:
    length = max(0, int(user32.GetWindowTextLengthW(window_handle)))
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(window_handle, buffer, len(buffer))
    return buffer.value


def _window_class(user32: Any, window_handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(window_handle, buffer, len(buffer))
    return buffer.value


def _control_details(x: int, y: int) -> dict[str, Any]:
    try:
        import uiautomation as auto

        control = auto.ControlFromPoint(int(x), int(y))
        if control is None:
            return {}
        rect = getattr(control, "BoundingRectangle", None)
        details: dict[str, Any] = {
            "name": str(getattr(control, "Name", "") or "")[:500],
            "control_type": str(getattr(control, "ControlTypeName", "") or ""),
            "class_name": str(getattr(control, "ClassName", "") or ""),
            "automation_id": str(getattr(control, "AutomationId", "") or ""),
        }
        if rect is not None:
            details["rect"] = [
                int(getattr(rect, "left", 0)),
                int(getattr(rect, "top", 0)),
                int(getattr(rect, "right", 0)),
                int(getattr(rect, "bottom", 0)),
            ]
        return details
    except Exception as exc:
        return {"inspection_error": str(exc)[:500]}


def _capture_window_screenshot(
    destination: Path,
    rect: tuple[int, int, int, int],
) -> str:
    try:
        from PIL import ImageGrab

        left, top, right, bottom = rect
        image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        image.save(destination, format="JPEG", quality=82, optimize=True)
        return destination.name
    except Exception:
        return ""


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def record_jianying_interactions(
    output_root: Path | str,
    *,
    timeout_seconds: int = 600,
    max_events: int = 100,
    settle_seconds: float = 1.0,
) -> Path:
    """Record clicks inside JianYing until F8 is pressed and return report path.

    Keyboard input is intentionally not recorded. A cropped screenshot of the
    JianYing window is saved after each accepted click.
    """

    if os.name != "nt":
        raise RuntimeError("剪映操作录制只能在 Windows 上使用")

    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    _set_dpi_awareness(user32)

    started_at = time.time()
    timestamp = datetime.fromtimestamp(started_at).strftime("%Y%m%d-%H%M%S")
    session_dir = Path(output_root).expanduser().resolve() / f"jianying-{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=False)
    report_path = session_dir / "interaction-report.json"
    report: dict[str, Any] = {
        "format": "jianying-interaction-recording-v1",
        "started_at": started_at,
        "finished_at": None,
        "stop_key": STOP_KEY,
        "keyboard_text_recorded": False,
        "events": [],
    }
    _write_report(report_path, report)

    time.sleep(max(0.2, float(settle_seconds)))
    deadline = time.monotonic() + max(30, int(timeout_seconds))
    button_states = {
        "left": bool(user32.GetAsyncKeyState(_LEFT_VIRTUAL_KEY) & 0x8000),
        "right": bool(user32.GetAsyncKeyState(_RIGHT_VIRTUAL_KEY) & 0x8000),
    }
    stop_was_down = bool(user32.GetAsyncKeyState(_STOP_VIRTUAL_KEY) & 0x8000)
    stop_reason = "timeout"

    while time.monotonic() < deadline and len(report["events"]) < max(1, int(max_events)):
        stop_is_down = bool(user32.GetAsyncKeyState(_STOP_VIRTUAL_KEY) & 0x8000)
        if stop_is_down and not stop_was_down:
            stop_reason = "hotkey"
            break
        stop_was_down = stop_is_down

        for button, virtual_key in (("left", _LEFT_VIRTUAL_KEY), ("right", _RIGHT_VIRTUAL_KEY)):
            is_down = bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)
            pressed = is_down and not button_states[button]
            button_states[button] = is_down
            if pressed:
                point = wintypes.POINT()
                if not user32.GetCursorPos(ctypes.byref(point)):
                    continue
                child = user32.WindowFromPoint(point)
                root = user32.GetAncestor(child, 2) if child else 0
                process = _process_basename(root) if root else ""
                if not root or process not in JIANYING_PROCESSES:
                    continue
                rect_value = wintypes.RECT()
                if not user32.GetWindowRect(root, ctypes.byref(rect_value)):
                    continue
                rect = (
                    int(rect_value.left),
                    int(rect_value.top),
                    int(rect_value.right),
                    int(rect_value.bottom),
                )
                try:
                    position = normalize_recorded_point(point.x, point.y, rect)
                except ValueError:
                    continue
                event_number = len(report["events"]) + 1
                event = {
                    "sequence": event_number,
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                    "button": button,
                    "process": process,
                    "window_title": _window_text(user32, root)[:500],
                    "window_class": _window_class(user32, root),
                    "window_rect": list(rect),
                    "position": position,
                    "control": _control_details(point.x, point.y),
                    "screenshot": "",
                }
                # Let the click change the screen before taking the diagnostic image.
                time.sleep(0.18)
                screenshot = session_dir / f"event-{event_number:03d}.jpg"
                event["screenshot"] = _capture_window_screenshot(screenshot, rect)
                report["events"].append(event)
                _write_report(report_path, report)
        time.sleep(0.015)
    else:
        if len(report["events"]) >= max(1, int(max_events)):
            stop_reason = "event_limit"

    report["finished_at"] = time.time()
    report["stop_reason"] = stop_reason
    report["event_count"] = len(report["events"])
    _write_report(report_path, report)
    return report_path
