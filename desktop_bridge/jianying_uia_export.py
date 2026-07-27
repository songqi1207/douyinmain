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

    window = _wait_for_window(auto, "home", 15)
    window.SetActive()
    window.SetTopmost()
    _emit(stage, "uia2_home_ready", f"class={window.ClassName}")

    draft_title = window.TextControl(
        searchDepth=8,
        Compare=_description_matcher(
            f"HomePageDraftTitle:{draft_name}",
            exact=True,
        ),
    )
    if not draft_title.Exists(15, 0.25):
        raise JianyingUIAError(f"UIA2 没有找到草稿卡片“{draft_name}”")
    draft_button = draft_title.GetParentControl()
    if draft_button is None:
        draft_button = draft_title
    draft_button.Click(simulateMove=False)
    _emit(stage, "uia2_draft_opened")

    editor = _wait_for_window(auto, "edit", 120)
    editor.SetActive()
    export_button = editor.TextControl(
        searchDepth=8,
        Compare=_description_matcher("MainWindowTitleBarExportBtn"),
    )
    if not export_button.Exists(10, 0.25):
        raise JianyingUIAError("UIA2 没有找到编辑页导出按钮")
    export_button.Click(simulateMove=False)
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
    _emit(stage, "uia2_export_completed", f"size_bytes={target.stat().st_size}")
    return target
