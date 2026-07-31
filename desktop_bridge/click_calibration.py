"""Opt-in two-step calibration for JianYing export automation."""

from __future__ import annotations

import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path


CALIBRATION_KEY = "jianying_export_click_calibration"
CONFIRM_CALIBRATION_KEY = "jianying_export_confirm_calibration"


def normalize_export_click(
    x: int,
    y: int,
    rect: tuple[int, int, int, int],
) -> dict[str, float | int]:
    left, top, right, bottom = (int(value) for value in rect)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0 or not (left <= x <= right and top <= y <= bottom):
        raise ValueError("点击位置不在有效的剪映窗口内")
    return {
        "x_from_right_ratio": round((right - int(x)) / width, 6),
        "y_from_top_ratio": round((int(y) - top) / height, 6),
        "window_width": width,
        "window_height": height,
        "recorded_at": int(time.time()),
    }


def valid_export_calibration(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x_ratio = float(value.get("x_from_right_ratio"))
        y_ratio = float(value.get("y_from_top_ratio"))
    except (TypeError, ValueError):
        return None
    if not (0.01 <= x_ratio <= 0.5 and 0.0 <= y_ratio <= 0.25):
        return None
    return {
        "x_from_right_ratio": x_ratio,
        "y_from_top_ratio": y_ratio,
    }


def normalize_export_confirm_click(
    x: int,
    y: int,
    rect: tuple[int, int, int, int],
) -> dict[str, float | int]:
    left, top, right, bottom = (int(value) for value in rect)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0 or not (left <= x <= right and top <= y <= bottom):
        raise ValueError("点击位置不在有效的剪映导出窗口内")
    return {
        "x_from_right_ratio": round((right - int(x)) / width, 6),
        "y_from_bottom_ratio": round((bottom - int(y)) / height, 6),
        "window_width": width,
        "window_height": height,
        "recorded_at": int(time.time()),
    }


def valid_export_confirm_calibration(value: object) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x_ratio = float(value.get("x_from_right_ratio"))
        y_ratio = float(value.get("y_from_bottom_ratio"))
    except (TypeError, ValueError):
        return None
    if not (0.01 <= x_ratio <= 0.6 and 0.0 <= y_ratio <= 0.35):
        return None
    return {
        "x_from_right_ratio": x_ratio,
        "y_from_bottom_ratio": y_ratio,
    }


def load_export_calibration(settings_path: Path) -> dict[str, float] | None:
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return valid_export_calibration(payload.get(CALIBRATION_KEY))


def load_export_confirm_calibration(settings_path: Path) -> dict[str, float] | None:
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return valid_export_confirm_calibration(payload.get(CONFIRM_CALIBRATION_KEY))


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


def record_next_jianying_click(*, timeout_seconds: int = 60, settle_seconds: float = 1.2) -> dict:
    """Record one explicitly requested left-click inside a JianYing window."""

    if os.name != "nt":
        raise RuntimeError("剪映点击校准只能在 Windows 上使用")
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    time.sleep(max(0.5, float(settle_seconds)))
    deadline = time.monotonic() + max(10, int(timeout_seconds))
    left_was_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
    while time.monotonic() < deadline:
        if user32.GetAsyncKeyState(0x1B) & 0x8000:
            raise RuntimeError("已取消剪映点击校准")
        left_is_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        if left_is_down and not left_was_down:
            point = wintypes.POINT()
            if user32.GetCursorPos(ctypes.byref(point)):
                child = user32.WindowFromPoint(point)
                root = user32.GetAncestor(child, 2) if child else 0
                if root and _process_basename(root) in {"jianyingpro.exe", "capcut.exe"}:
                    rect = wintypes.RECT()
                    if user32.GetWindowRect(root, ctypes.byref(rect)):
                        return normalize_export_click(
                            point.x,
                            point.y,
                            (rect.left, rect.top, rect.right, rect.bottom),
                        )
        left_was_down = left_is_down
        time.sleep(0.02)
    raise RuntimeError("60 秒内没有检测到剪映窗口中的鼠标点击")


def record_jianying_export_clicks(
    *,
    timeout_seconds: int = 90,
    settle_seconds: float = 1.2,
) -> tuple[dict, dict]:
    """Record editor Export with left-click, then dialog Export with right-click."""

    if os.name != "nt":
        raise RuntimeError("剪映点击校准只能在 Windows 上使用")
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    def wait_for_click(virtual_key: int, deadline: float, label: str) -> tuple[int, int, tuple[int, int, int, int]]:
        was_down = bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)
        while time.monotonic() < deadline:
            if user32.GetAsyncKeyState(0x1B) & 0x8000:
                raise RuntimeError("已取消剪映点击校准")
            is_down = bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)
            if is_down and not was_down:
                point = wintypes.POINT()
                if user32.GetCursorPos(ctypes.byref(point)):
                    child = user32.WindowFromPoint(point)
                    root = user32.GetAncestor(child, 2) if child else 0
                    if root and _process_basename(root) in {"jianyingpro.exe", "capcut.exe"}:
                        rect = wintypes.RECT()
                        if user32.GetWindowRect(root, ctypes.byref(rect)):
                            return (
                                point.x,
                                point.y,
                                (rect.left, rect.top, rect.right, rect.bottom),
                            )
            was_down = is_down
            time.sleep(0.02)
        raise RuntimeError(f"超时：没有检测到剪映窗口中的{label}")

    time.sleep(max(0.5, float(settle_seconds)))
    deadline = time.monotonic() + max(20, int(timeout_seconds))
    editor_x, editor_y, editor_rect = wait_for_click(0x01, deadline, "第一次左键点击")
    editor = normalize_export_click(editor_x, editor_y, editor_rect)

    # Let JianYing finish opening the export dialog and wait for the left button
    # release, otherwise the second edge detector may see a stale mouse state.
    while user32.GetAsyncKeyState(0x01) & 0x8000:
        time.sleep(0.02)
    time.sleep(0.6)
    confirm_x, confirm_y, confirm_rect = wait_for_click(0x02, deadline, "第二次右键点击")
    confirm = normalize_export_confirm_click(confirm_x, confirm_y, confirm_rect)
    return editor, confirm
