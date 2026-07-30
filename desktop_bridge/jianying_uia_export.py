"""JianYing native export through the modern UI Automation COM client.

Newer QML builds can expose controls through UIAutomationCore while the legacy
``System.Windows.Automation`` client only sees the top-level window.  This
module is deliberately imported lazily by the device agent so non-Windows
server processes do not need to load COM.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Callable


FULL_DESCRIPTION_PROPERTY_ID = 30159
StageCallback = Callable[[str, str], None]


class JianyingUIAError(RuntimeError):
    """Raised when JianYing's UIA2 export route cannot complete."""


def _full_description(control: object) -> str:
    try:
        value = control.GetPropertyValue(FULL_DESCRIPTION_PROPERTY_ID)  # type: ignore[attr-defined]
    except Exception:
        return ""
    return str(value or "")


def _description_matcher(target: str, *, exact: bool = False):
    expected = str(target or "").casefold()

    def compare(control: object, _depth: int) -> bool:
        current = _full_description(control).casefold()
        return current == expected if exact else expected in current

    return compare


def _resolve_export_path(value: str, draft_name: str) -> Path:
    raw = str(value or "").strip().strip('"')
    if not raw:
        raise JianyingUIAError("剪映导出窗口没有返回保存路径")
    path = Path(raw).expanduser()
    if path.is_dir() or raw.endswith(("\\", "/")):
        path = path / f"{draft_name}.mp4"
    return path.resolve()


def _emit(callback: StageCallback | None, stage: str, details: str = "") -> None:
    if callback:
        callback(stage, details)


def _minimize_jianying_window(control: object, stage: StageCallback | None, reason: str) -> None:
    try:
        control.SetTopmost(False)  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        import ctypes

        handle = int(getattr(control, "NativeWindowHandle", 0) or 0)
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 6)
            _emit(stage, "uia2_jianying_minimized", f"reason={reason}")
    except Exception:
        # Export has already been triggered; restoring the desktop is best-effort.
        pass


def _force_foreground(control: object) -> None:
    try:
        import ctypes

        handle = int(getattr(control, "NativeWindowHandle", 0) or 0)
        if not handle:
            return
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 9)
        user32.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        time.sleep(0.12)
        user32.SetForegroundWindow(handle)
        time.sleep(0.25)
        user32.SetWindowPos(handle, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    except Exception:
        pass


def _first_draft_card_point(left: int, top: int, right: int, bottom: int) -> tuple[int, int]:
    width = max(1, int(right) - int(left))
    height = max(1, int(bottom) - int(top))
    return int(int(left) + (width * 0.255)), int(int(top) + (height * 0.775))


def _draft_card_candidate_points(left: int, top: int, right: int, bottom: int) -> list[tuple[int, int]]:
    width = max(1, int(right) - int(left))
    height = max(1, int(bottom) - int(top))
    ratios = [
        (0.255, 0.775),
        (0.335, 0.705),
        (0.255, 0.705),
        (0.335, 0.775),
        (0.205, 0.775),
        (0.395, 0.775),
    ]
    points: list[tuple[int, int]] = []
    for x_ratio, y_ratio in ratios:
        point = (int(int(left) + (width * x_ratio)), int(int(top) + (height * y_ratio)))
        if point not in points:
            points.append(point)
    return points


def _click_point(x: int, y: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def _control_rect(control: object) -> tuple[int, int, int, int] | None:
    try:
        rect = control.BoundingRectangle  # type: ignore[attr-defined]
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    except Exception:
        return None


def _click_control_center(control: object) -> bool:
    rect = _control_rect(control)
    if not rect:
        return False
    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return False
    x = int(left + ((right - left) * 0.50))
    y = int(top + ((bottom - top) * 0.38))
    _click_point(x, y)
    time.sleep(0.15)
    _click_point(x, y)
    return True


def _double_click_control(control: object) -> str:
    """Open a JianYing project card with UIA and robust fallbacks."""

    try:
        control.DoubleClick(waitTime=0.1)  # type: ignore[attr-defined]
        return "uia_double_click"
    except Exception:
        try:
            control.Click(simulateMove=False)  # type: ignore[attr-defined]
            time.sleep(0.15)
            control.Click(simulateMove=False)  # type: ignore[attr-defined]
            return "uia_click_twice"
        except Exception:
            if _click_control_center(control):
                return "coordinate_double_click"
            raise


def _first_home_project_item(window: object) -> object | None:
    def matcher(control: object, _depth: int) -> bool:
        return "HomePageOpenProjectItem".casefold() in str(
            getattr(control, "ClassName", "") or ""
        ).casefold()

    for factory_name in ("CustomControl", "GroupControl", "PaneControl", "Control"):
        factory = getattr(window, factory_name, None)
        if not factory:
            continue
        try:
            item = factory(searchDepth=8, Compare=matcher)
            if item.Exists(0):
                return item
        except Exception:
            continue
    return None


def _window_process_id(handle: int) -> int:
    import ctypes

    process_id = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(int(handle), ctypes.byref(process_id))
    return int(process_id.value)


def _dismiss_process_popups(reference_window: object, stage: StageCallback | None) -> int:
    import ctypes

    reference_handle = int(getattr(reference_window, "NativeWindowHandle", 0) or 0)
    if not reference_handle:
        return 0
    process_id = _window_process_id(reference_handle)
    if not process_id:
        return 0

    user32 = ctypes.windll.user32
    closed = 0
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    @EnumWindowsProc
    def enum_proc(hwnd, _lparam):
        nonlocal closed
        if not user32.IsWindowVisible(hwnd):
            return True
        if _window_process_id(hwnd) != process_id:
            return True
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        class_name = class_buffer.value or ""
        if (
            hwnd != reference_handle
            and any(token in class_name for token in ("LVInfoDialog", "SplashDialog", "Popup"))
            and "ExportWindow" not in class_name
        ):
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
            _emit(stage, "uia2_popup_dismissed", f"mode=window_close class={class_name}")
            width = max(1, int(rect.right) - int(rect.left))
            height = max(1, int(rect.bottom) - int(rect.top))
            x = int(rect.right - min(230, max(80, width * 0.33)))
            y = int(rect.bottom - min(55, max(35, height * 0.12)))
            _click_point(x, y)
            _emit(stage, "uia2_popup_dismissed", f"mode=coordinate class={class_name} x={x} y={y}")
            closed += 1
        return True

    user32.EnumWindows(enum_proc, 0)
    if closed:
        time.sleep(0.8)
    return closed


def _window_rect(window: object) -> tuple[int, int, int, int]:
    import ctypes

    handle = int(getattr(window, "NativeWindowHandle", 0) or 0)
    if not handle:
        raise JianyingUIAError("UIA2 无法读取剪映首页窗口句柄")
    user32 = ctypes.windll.user32
    _force_foreground(window)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise JianyingUIAError("UIA2 无法读取剪映首页窗口位置")
    if rect.left < -30000 or rect.top < -30000 or rect.right <= rect.left or rect.bottom <= rect.top:
        user32.ShowWindow(handle, 3)
        user32.SetForegroundWindow(handle)
        time.sleep(0.5)
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            raise JianyingUIAError("UIA2 无法读取剪映首页窗口位置")
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _open_home_draft_by_coordinate(auto, window: object, stage: StageCallback | None):
    _force_foreground(window)
    project_item = _first_home_project_item(window)
    if project_item is not None:
        _dismiss_process_popups(window, stage)
        _emit(
            stage,
            "uia2_draft_card_fallback_item",
            f"class={getattr(project_item, 'ClassName', '')}",
        )
        mode = _double_click_control(project_item)
        _emit(stage, "uia2_draft_card_fallback_opened", f"mode={mode}")
        return _wait_for_window(auto, "edit", 30)

    rect = _window_rect(window)
    for index, (x, y) in enumerate(_draft_card_candidate_points(*rect), start=1):
        _dismiss_process_popups(window, stage)
        _emit(stage, "uia2_draft_card_coordinate_click", f"attempt={index} x={x} y={y}")
        _click_point(x, y)
        time.sleep(0.15)
        _click_point(x, y)
        try:
            return _wait_for_window(auto, "edit", 8)
        except JianyingUIAError:
            try:
                current_window, current_state = _get_window(auto)
                if current_state != "home":
                    return _wait_for_window(auto, "edit", 8)
                current_window.SetActive()
                current_window.SetTopmost()
            except JianyingUIAError:
                pass
    raise JianyingUIAError("UIA2 坐标兜底点击后仍未进入草稿编辑页")


def _get_window(auto):
    state = {"value": ""}

    def window_matcher(control, depth: int) -> bool:
        if depth != 1 or str(control.Name or "") != "剪映专业版":
            return False
        class_name = str(control.ClassName or "")
        if "HomePage".casefold() in class_name.casefold():
            state["value"] = "home"
            return True
        if "MainWindow".casefold() in class_name.casefold():
            state["value"] = "edit"
            return True
        return False

    window = auto.WindowControl(searchDepth=1, Compare=window_matcher)
    if not window.Exists(2, 0.2):
        raise JianyingUIAError("UIA2 没有找到剪映主页或编辑窗口")

    export_window = window.WindowControl(searchDepth=2, Name="导出")
    if export_window.Exists(0):
        return export_window, "pre_export"
    return window, state["value"]


def _wait_for_window(auto, expected: str, timeout: float):
    deadline = time.monotonic() + timeout
    last_state = ""
    while time.monotonic() < deadline:
        try:
            window, state = _get_window(auto)
            last_state = state
            if state == expected:
                return window
        except JianyingUIAError:
            pass
        time.sleep(0.5)
    raise JianyingUIAError(
        f"等待剪映窗口状态超时：需要 {expected}，当前 {last_state or 'unknown'}"
    )


def _close_success_dialog(auto, stage: StageCallback | None) -> bool:
    try:
        window, state = _get_window(auto)
    except JianyingUIAError:
        return False
    if state != "pre_export":
        return False

    success_text = window.TextControl(
        searchDepth=8,
        Compare=lambda control, _depth: any(
            text.casefold() in str(control.Name or "").casefold()
            or text.casefold() in _full_description(control).casefold()
            for text in ("导出成功", "让更多人看到你的作品", "查看草稿", "Export succeeded")
        ),
    )
    if not success_text.Exists(0):
        return False

    close_button = window.TextControl(
        searchDepth=8,
        Compare=lambda control, _depth: str(control.Name or "").strip().casefold()
        in {"关闭", "完成", "close", "done", "ok"},
    )
    if close_button.Exists(1, 0.2):
        close_button.Click(simulateMove=False)
        _emit(stage, "uia2_success_dialog_closed", "mode=button")
        time.sleep(0.8)
        return True

    try:
        import ctypes

        handle = int(getattr(window, "NativeWindowHandle", 0) or 0)
        if handle:
            ctypes.windll.user32.PostMessageW(handle, 0x0010, 0, 0)
            _emit(stage, "uia2_success_dialog_closed", "mode=close_message")
            time.sleep(0.8)
            return True
    except Exception:
        pass
    return False


def export_draft_uia(
    draft_name: str,
    output_path: Path | str,
    *,
    timeout: int = 1800,
    stage: StageCallback | None = None,
) -> Path:
    """Open ``draft_name`` in JianYing, export it, and return the task MP4."""

    try:
        import uiautomation as auto
    except ImportError as exc:  # pragma: no cover - guarded by packaged build
        raise JianyingUIAError("助手未包含 UIA2 自动化组件") from exc

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _emit(stage, "uia2_started", f"draft_name={draft_name}")

    try:
        current_window, current_state = _get_window(auto)
    except JianyingUIAError:
        current_window, current_state = _wait_for_window(auto, "home", 15), "home"
    if current_state == "pre_export" and _close_success_dialog(auto, stage):
        try:
            current_window, current_state = _get_window(auto)
        except JianyingUIAError:
            current_window, current_state = _wait_for_window(auto, "home", 15), "home"

    if current_state == "home":
        window = current_window
        window.SetActive()
        window.SetTopmost()
        _dismiss_process_popups(window, stage)
        _emit(stage, "uia2_home_ready", f"class={window.ClassName}")

        draft_title = window.TextControl(
            searchDepth=8,
            Compare=_description_matcher(
                f"HomePageDraftTitle:{draft_name}",
                exact=True,
            ),
        )
        if not draft_title.Exists(15, 0.25):
            _emit(stage, "uia2_draft_card_not_found", f"draft_name={draft_name}")
            _dismiss_process_popups(window, stage)
            editor = _open_home_draft_by_coordinate(auto, window, stage)
            _emit(stage, "uia2_draft_opened", "mode=coordinate")
        else:
            draft_button = draft_title.GetParentControl()
            if draft_button is None:
                draft_button = draft_title
            mode = _double_click_control(draft_button)
            _emit(stage, "uia2_draft_open_attempted", f"mode={mode}")
            try:
                editor = _wait_for_window(auto, "edit", 25)
            except JianyingUIAError:
                _emit(stage, "uia2_draft_open_retry", f"draft_name={draft_name}")
                _dismiss_process_popups(window, stage)
                editor = _open_home_draft_by_coordinate(auto, window, stage)
                mode = "coordinate_retry"
            _emit(stage, "uia2_draft_opened", f"mode={mode}")
    elif current_state == "edit":
        editor = current_window
        _emit(stage, "uia2_editor_reused", f"class={editor.ClassName}")
    elif current_state == "pre_export":
        export_window = current_window
        _emit(stage, "uia2_export_dialog_reused")
    else:
        raise JianyingUIAError(f"UIA2 不支持的剪映窗口状态：{current_state or 'unknown'}")

    if current_state != "pre_export":
        editor.SetActive()
        editor.SetTopmost()
        export_button = editor.TextControl(
            searchDepth=8,
            Compare=_description_matcher("MainWindowTitleBarExportBtn"),
        )
        if export_button.Exists(10, 0.25):
            export_button.Click(simulateMove=False)
        else:
            try:
                import uiautomation as auto_module

                auto_module.SendKeys("{Ctrl}e")
            except Exception as exc:
                raise JianyingUIAError("UIA2 没有找到编辑页导出按钮") from exc
            _emit(stage, "uia2_export_shortcut", "key=ctrl+e")
        _emit(stage, "uia2_export_dialog_opening")
        export_window = _wait_for_window(auto, "pre_export", 30)
    path_label = export_window.TextControl(
        searchDepth=8,
        Compare=_description_matcher("ExportPath"),
    )
    if not path_label.Exists(10, 0.25):
        raise JianyingUIAError("UIA2 没有找到导出保存位置")
    path_value = path_label.GetSiblingControl(lambda _control: True)
    if path_value is None:
        raise JianyingUIAError("UIA2 没有找到导出路径输入控件")
    source = _resolve_export_path(_full_description(path_value), draft_name)
    _emit(stage, "uia2_export_path_ready", f"path={source}")

    confirm = export_window.TextControl(
        searchDepth=8,
        Compare=_description_matcher("ExportOkBtn", exact=True),
    )
    if not confirm.Exists(10, 0.25):
        raise JianyingUIAError("UIA2 没有找到导出确认按钮")
    confirm.Click(simulateMove=False)
    _emit(stage, "uia2_export_confirmed")
    _minimize_jianying_window(export_window, stage, "export_wait")

    deadline = time.monotonic() + max(30, int(timeout))
    last_size = -1
    stable_count = 0
    while time.monotonic() < deadline:
        try:
            current_window, current_state = _get_window(auto)
            if current_state == "pre_export":
                close_button = current_window.TextControl(
                    searchDepth=8,
                    Compare=_description_matcher(
                        "ExportSucceedCloseBtn",
                        exact=True,
                    ),
                )
                if close_button.Exists(0):
                    close_button.Click(simulateMove=False)
                    _emit(stage, "uia2_success_dialog_closed")
        except JianyingUIAError:
            pass

        if source.is_file():
            size = source.stat().st_size
            if size > 0 and size == last_size:
                stable_count += 1
                if stable_count >= 3:
                    break
            else:
                stable_count = 0
            last_size = size
        time.sleep(1)
    else:
        raise JianyingUIAError(f"剪映导出超时，未生成文件：{source}")

    if target.exists():
        target.unlink()
    if source != target:
        shutil.move(str(source), str(target))
    if not target.is_file() or target.stat().st_size <= 0:
        raise JianyingUIAError("UIA2 导出结束，但任务 MP4 文件无效")
    try:
        current_window, _state = _get_window(auto)
        _minimize_jianying_window(current_window, stage, "completed")
    except Exception:
        pass
    _emit(stage, "uia2_export_completed", f"size_bytes={target.stat().st_size}")
    return target
