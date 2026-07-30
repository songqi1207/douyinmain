"""Outbound-only render agent for a user's own Windows computer."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

import requests

from desktop_bridge.draft_core import BridgeError, import_draft_payload
from desktop_bridge.helper_metadata import HELPER_VERSION
from desktop_bridge.paths import app_data_dir


StatusCallback = Callable[[str], None]
logger = logging.getLogger("douyin.render_agent")
logger.addHandler(logging.NullHandler())


def agent_log_path() -> Path:
    return (app_data_dir() / "logs" / "render-agent.log").resolve()


def _configure_agent_logging() -> None:
    if any(getattr(handler, "_douyin_render_agent", False) for handler in logger.handlers):
        return
    path = agent_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler._douyin_render_agent = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel((os.getenv("DEVICE_AGENT_LOG_LEVEL") or "INFO").upper())
    logger.propagate = False


def normalize_site_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if url.endswith("/business"):
        url = url[:-9]
    if not url.startswith(("http://", "https://")):
        raise BridgeError("网站地址必须以 http:// 或 https:// 开头")
    return url


def pair_with_site(site_url: str, code: str, device_name: str) -> dict:
    url = normalize_site_url(site_url)
    try:
        response = requests.post(
            f"{url}/api/v1/render-agent/pair",
            json={
                "code": str(code or "").strip().upper(),
                "name": str(device_name or "").strip() or platform.node() or "我的电脑",
                "platform": "windows",
                "capabilities": {
                    "jianying_native_export": True,
                    "ffmpeg": False,
                    "helper_version": HELPER_VERSION,
                },
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise BridgeError(f"无法连接网站：{exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail") or {}
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except ValueError:
            message = response.text
        raise BridgeError(str(message or f"配对失败（HTTP {response.status_code}）"))
    result = response.json()
    if not result.get("device_id") or not result.get("device_token"):
        raise BridgeError("网站没有返回有效的设备授权")
    return {**result, "site_url": url}


def _resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        return (Path(getattr(sys, "_MEIPASS")) / relative).resolve()
    return (Path(__file__).resolve().parents[1] / relative).resolve()


def _run_pyjianying_export(
    draft_name: str,
    output_path: Path,
    executable: Path,
    timeout: int,
    job_id: str,
) -> Path:
    """Export through pyJianYingDraft before using our compatibility drivers."""
    skip_py_export = (
        os.getenv("DEVICE_JIANYING_SKIP_PY_EXPORT") or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if skip_py_export:
        logger.info("pyjianying_export_skipped job_id=%s reason=env", job_id)
        raise BridgeError("pyJianYingDraft export skipped by configuration")

    try:
        from pyJianYingDraft import JianyingController
    except ImportError as exc:
        raise BridgeError("助手缺少 pyJianYingDraft 导出组件") from exc

    controller = None
    last_error: Exception | None = None
    try:
        controller = JianyingController()
    except Exception as exc:
        last_error = exc

    if controller is None:
        logger.info(
            "pyjianying_starting_jianying job_id=%s executable=%s",
            job_id,
            executable,
        )
        subprocess.Popen(
            [
                str(executable),
                "--force-renderer-accessibility",
                "--enable-accessibility",
            ],
            cwd=str(executable.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + int(
            os.getenv("DEVICE_JIANYING_START_TIMEOUT_SECONDS") or 60
        )
        while time.monotonic() < deadline:
            try:
                controller = JianyingController()
                break
            except Exception as exc:
                last_error = exc
                time.sleep(1)

    if controller is None:
        raise BridgeError(f"pyJianYingDraft 没有找到剪映窗口：{last_error}")

    logger.info(
        "pyjianying_export_started job_id=%s draft_name=%s timeout_seconds=%s",
        job_id,
        draft_name,
        timeout,
    )
    started_at = time.monotonic()
    draft_wait_deadline = time.monotonic() + int(
        os.getenv("DEVICE_JIANYING_DRAFT_WAIT_SECONDS") or 12
    )
    retry_interval = max(
        0.0,
        float(os.getenv("DEVICE_JIANYING_DRAFT_RETRY_SECONDS") or 1.5),
    )
    attempt = 0
    while True:
        attempt += 1
        try:
            controller.export_draft(
                draft_name,
                str(output_path),
                timeout=timeout,
            )
            break
        except Exception as exc:
            if exc.__class__.__name__ != "DraftNotFound":
                raise
            remaining = draft_wait_deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "pyjianying_draft_wait_timeout job_id=%s draft_name=%s attempts=%s",
                    job_id,
                    draft_name,
                    attempt,
                )
                raise
            logger.info(
                "pyjianying_waiting_for_draft job_id=%s draft_name=%s attempt=%s remaining_seconds=%.1f",
                job_id,
                draft_name,
                attempt,
                remaining,
            )
            time.sleep(min(retry_interval, remaining))
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise BridgeError("pyJianYingDraft 已完成操作，但没有生成有效的 MP4 文件")
    logger.info(
        "pyjianying_export_finished job_id=%s size_bytes=%s elapsed_seconds=%.3f",
        job_id,
        output_path.stat().st_size,
        time.monotonic() - started_at,
    )
    try:
        import ctypes

        controller.get_window()
        controller.app.SetTopmost(False)
        handle = int(getattr(controller.app, "NativeWindowHandle", 0) or 0)
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 6)
    except Exception:
        pass
    return output_path


def _run_native_export(
    task: dict,
    draft_root: str,
    jianying_exe: str,
    output_dir: Path,
    progress: StatusCallback | None = None,
) -> Path:
    started_at = time.monotonic()
    if os.name != "nt":
        raise BridgeError("本机剪映导出助手只能在 Windows 上运行")
    root = Path(draft_root).expanduser().resolve()
    executable = Path(jianying_exe).expanduser().resolve()
    if not root.is_dir():
        raise BridgeError(f"剪映草稿目录不存在：{root}")
    if not executable.is_file():
        raise BridgeError(f"剪映专业版程序不存在：{executable}")

    if progress:
        progress("正在把任务写入本机剪映草稿…")
    logger.info("draft_import_started job_id=%s", task.get("job_id"))
    report = import_draft_payload(
        task.get("draft_key"),
        draft_root=root,
        force=True,
        progress=progress,
    )
    draft_name = str(report.get("draft_name") or "").strip()
    if not draft_name:
        raise BridgeError("草稿导入成功，但没有得到剪映草稿名称")
    logger.info(
        "draft_import_finished job_id=%s draft_id=%s draft_dir=%s tracks=%s segments=%s warnings=%s elapsed_seconds=%.3f",
        task.get("job_id"),
        report.get("draft_id") or "-",
        report.get("draft_dir") or "-",
        report.get("track_count", "-"),
        report.get("segment_count", "-"),
        len(report.get("warnings") or []),
        time.monotonic() - started_at,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / f"{task['job_id']}.mp4").resolve()
    automation = _resource_path("scripts/run_jianying_export_automation.ps1")
    if output_path.exists():
        output_path.unlink()

    if progress:
        progress(f"正在用剪映专业版导出“{draft_name}”…")
    export_timeout = int(os.getenv("DEVICE_JIANYING_EXPORT_TIMEOUT_SECONDS") or 1800)
    job_id = str(task.get("job_id") or "-")
    if progress:
        progress("正在使用 pyJianYingDraft 导出视频…")
    try:
        return _run_pyjianying_export(
            draft_name,
            output_path,
            executable,
            export_timeout,
            job_id,
        )
    except Exception as exc:
        logger.warning(
            "pyjianying_export_failed job_id=%s fallback=compatibility_driver error=%s",
            job_id,
            exc,
        )
        if output_path.exists():
            output_path.unlink()
        allow_foreground = (
            os.getenv("DEVICE_JIANYING_ALLOW_FOREGROUND_AUTOMATION") or "1"
        ).strip().lower()
        if allow_foreground in {"0", "false", "no", "off"}:
            raise BridgeError(
                "pyJianYingDraft could not complete the native export. "
                "Foreground Jianying UI automation is disabled by "
                "DEVICE_JIANYING_ALLOW_FOREGROUND_AUTOMATION=0, so the helper "
                "will not pop up Jianying on this desktop. Use a dedicated "
                "Windows machine/VM for invisible exports, or re-enable "
                "foreground automation."
            ) from exc
        if progress:
            progress("pyJianYingDraft 未能完成导出，正在切换兼容模式…")

    if not automation.is_file():
        raise BridgeError(f"剪映自动导出脚本不存在：{automation}")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(automation),
        "-DraftName",
        draft_name,
        "-OutputPath",
        str(output_path),
        "-JianyingExe",
        str(executable),
        "-LogPath",
        str(agent_log_path()),
        "-TimeoutSeconds",
        str(export_timeout),
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def run_compatibility_export(
        command_args: list[str],
        *,
        log_prefix: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        export_started_at = time.monotonic()
        logger.info("%s_started job_id=%s", log_prefix, job_id)
        completed_process = subprocess.run(
            command_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=export_timeout + 60,
            creationflags=flags,
        )
        logger.info(
            "%s_finished job_id=%s returncode=%s elapsed_seconds=%.3f",
            log_prefix,
            job_id,
            completed_process.returncode,
            time.monotonic() - export_started_at,
        )
        parsed_stage_lines = [
            line.strip()
            for line in (completed_process.stdout or "").splitlines()
            if "jianying_automation_stage" in line
        ]
        for output_line in parsed_stage_lines:
            if output_line:
                logger.info(
                    "%s_output job_id=%s %s",
                    log_prefix,
                    job_id,
                    output_line,
                )
        return completed_process, parsed_stage_lines

    fast_compatibility_path = (
        os.getenv("DEVICE_JIANYING_SKIP_PY_EXPORT") or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    restart_first = (os.getenv("DEVICE_JIANYING_RESTART_FIRST") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    initial_command = [*command, "-RestartExisting"] if (fast_compatibility_path or restart_first) else command
    if fast_compatibility_path:
        logger.info(
            "jianying_fast_path_restart_enabled job_id=%s draft_name=%s",
            job_id,
            draft_name,
        )
    completed, stage_lines = run_compatibility_export(
        initial_command,
        log_prefix="jianying_export",
    )
    stage_output = "\n".join(stage_lines)
    if (
        completed.returncode != 0
        and "stage=ui_tree_unavailable action=restart_with_helper" in stage_output
    ):
        logger.info(
            "jianying_accessibility_restart_started job_id=%s",
            task.get("job_id"),
        )
        if progress:
            progress("剪映未开放内部控件，正在完整重启剪映后重试…")
        completed, stage_lines = run_compatibility_export(
            [*command, "-RestartExisting"],
            log_prefix="jianying_accessibility_restart",
        )
    stage_output = "\n".join(stage_lines)
    restartable_window_state = (
        completed.returncode != 0
        and (
            "stage=draft_card_not_found" in stage_output
            or "stage=editor_already_open" in stage_output
        )
        and "stage=restarting_existing_jianying" not in stage_output
    )
    if restartable_window_state:
        logger.info(
            "jianying_draft_refresh_restart_started job_id=%s draft_name=%s",
            job_id,
            draft_name,
        )
        if progress:
            progress("剪映没有刷新出新草稿，正在重启剪映后重试导出...")
        completed, stage_lines = run_compatibility_export(
            [*command, "-RestartExisting"],
            log_prefix="jianying_draft_refresh_restart",
        )
    if completed.returncode != 0:
        stage_output = "\n".join(stage_lines)
        uia2_markers = (
            "stage=ui_tree_unavailable",
            "stage=draft_card_not_found",
            "stage=editor_export_button_not_found",
        )
        if any(marker in stage_output for marker in uia2_markers):
            from desktop_bridge.jianying_uia_export import (
                JianyingUIAError,
                export_draft_uia,
            )

            logger.info(
                "jianying_uia2_fallback_started job_id=%s",
                task.get("job_id"),
            )

            def log_uia2_stage(stage_name: str, details: str = "") -> None:
                suffix = f" {details}" if details else ""
                logger.info(
                    "jianying_uia2_stage job_id=%s stage=%s%s",
                    task.get("job_id"),
                    stage_name,
                    suffix,
                )

            try:
                result = export_draft_uia(
                    draft_name,
                    output_path,
                    timeout=int(
                        os.getenv("DEVICE_JIANYING_EXPORT_TIMEOUT_SECONDS") or 1800
                    ),
                    stage=log_uia2_stage,
                )
                logger.info(
                    "jianying_uia2_fallback_finished job_id=%s size_bytes=%s",
                    task.get("job_id"),
                    result.stat().st_size,
                )
                return result
            except JianyingUIAError as exc:
                logger.warning(
                    "jianying_uia2_fallback_failed job_id=%s error=%s",
                    task.get("job_id"),
                    exc,
                )
                raise BridgeError(
                    f"剪映 UIA2 自动导出失败：{exc}"
                ) from exc
        if "stage=ui_tree_unavailable" in stage_output:
            if "action=restart_with_helper" in stage_output:
                raise BridgeError(
                    "剪映已打开，但没有向助手开放内部控件。请完全退出剪映（包括后台进程）"
                    "后重试，让助手使用可访问性模式重新启动剪映；不要让剪映和助手一个"
                    "“以管理员身份运行”、另一个普通运行。"
                )
            raise BridgeError(
                "剪映没有向助手开放内部控件，无法自动点击草稿和导出按钮。"
                "当前剪映 7+ 版本可能隐藏了自动化控件；请改用剪映专业版 5.9，"
                "或确认剪映与助手使用相同的运行权限。"
            )
        if "stage=draft_card_not_found" in stage_output:
            raise BridgeError(
                "剪映首页没有识别到目标草稿卡片。请确认助手使用的草稿目录与"
                "剪映“全局设置 > 草稿位置”一致；可见控件快照已写入助手日志。"
            )
        if "stage=editor_already_open" in stage_output:
            raise BridgeError(
                "剪映当前停留在草稿编辑页。请返回本地草稿首页后重试任务。"
            )
        if "stage=editor_export_button_not_found" in stage_output:
            raise BridgeError(
                "草稿已经打开，但没有识别到编辑页的导出按钮。"
                "请关闭剪映弹窗并确认已进入草稿编辑页后重试。"
            )
        message = (completed.stderr or completed.stdout or "剪映自动导出失败").strip()
        raise BridgeError(message[-2000:])
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise BridgeError("剪映导出流程已结束，但没有生成 MP4 文件")
    return output_path


class DeviceAgent:
    def __init__(
        self,
        *,
        site_url: str,
        device_id: str,
        device_token: str,
        draft_root: str,
        jianying_exe: str,
        status: StatusCallback | None = None,
    ):
        self.site_url = normalize_site_url(site_url)
        self.device_id = str(device_id)
        self.device_token = str(device_token)
        self.draft_root = str(draft_root)
        self.jianying_exe = str(jianying_exe)
        self.status = status
        _configure_agent_logging()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.device_token}"})
        self.output_dir = (app_data_dir() / "output").resolve()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        logger.info(
            "agent_started version=%s device_id=%s site=%s",
            HELPER_VERSION,
            self.device_id,
            self.site_url,
        )
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="jianying-device-agent")
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="jianying-device-heartbeat",
        )
        self._heartbeat_thread.start()
        self._thread.start()

    def stop(self) -> None:
        logger.info("agent_stopping device_id=%s", self.device_id)
        self._stop.set()

    def _set_status(self, message: str) -> None:
        if self.status:
            self.status(message)

    def _request(self, method: str, path: str, **kwargs):
        timeout = kwargs.pop("timeout", 30)
        return self._session.request(method, f"{self.site_url}{path}", timeout=timeout, **kwargs)

    def _loop(self) -> None:
        self._set_status("本机剪映助手正在连接网站…")
        while not self._stop.is_set():
            try:
                response = self._request("POST", "/api/v1/render-agent/claim")
                if response.status_code == 204:
                    self._stop.wait(4)
                    continue
                if response.status_code == 401:
                    self._set_status("设备授权已失效，请重新输入配对码")
                    return
                response.raise_for_status()
                task = (response.json() or {}).get("task")
                if not isinstance(task, dict):
                    self._stop.wait(4)
                    continue
                logger.info(
                    "device_task_claimed job_id=%s workflow=%s",
                    task.get("job_id"),
                    task.get("workflow_code"),
                )
                self._process_task(task)
            except requests.RequestException as exc:
                logger.warning("agent_request_failed error=%s", exc)
                self._set_status(f"网站暂时无法连接，稍后自动重试：{exc}")
                self._stop.wait(10)
            except Exception as exc:
                logger.exception("agent_loop_failed error=%s", exc)
                self._set_status(f"本机助手异常，稍后自动重试：{exc}")
                self._stop.wait(10)

    def _heartbeat_loop(self) -> None:
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {self.device_token}"})
        announced = False
        while not self._stop.is_set():
            try:
                response = session.post(
                    f"{self.site_url}/api/v1/render-agent/heartbeat",
                    json={
                        "capabilities": {
                            "jianying_native_export": True,
                            "ffmpeg": False,
                            "jianying_found": Path(self.jianying_exe).is_file(),
                            "helper_version": HELPER_VERSION,
                        }
                    },
                    timeout=30,
                )
                if response.status_code == 401:
                    self._set_status("设备授权已失效，请重新输入配对码")
                    self._stop.set()
                    return
                response.raise_for_status()
                if not announced:
                    self._set_status("本机剪映助手在线，等待网站任务")
                    announced = True
            except requests.RequestException as exc:
                if not announced:
                    self._set_status(f"网站暂时无法连接，稍后自动重试：{exc}")
            self._stop.wait(30)

    def _process_task(self, task: dict) -> None:
        job_id = str(task.get("job_id") or "")
        if not job_id:
            return
        try:
            output_path = _run_native_export(
                task,
                self.draft_root,
                self.jianying_exe,
                self.output_dir,
                self._set_status,
            )
            self._set_status("剪映导出完成，正在把视频传回网站…")
            with output_path.open("rb") as stream:
                response = self._request(
                    "POST",
                    f"/api/v1/render-agent/jobs/{job_id}/complete",
                    files={"video": (output_path.name, stream, "video/mp4")},
                    timeout=int(os.getenv("DEVICE_RESULT_UPLOAD_TIMEOUT_SECONDS") or 1800),
                )
            response.raise_for_status()
            logger.info("device_task_completed job_id=%s", job_id)
            self._set_status("视频已传回网站，可以直接预览和下载")
        except Exception as exc:
            message = str(exc) or "本机剪映导出失败"
            logger.exception("device_task_failed job_id=%s error=%s", job_id, message)
            try:
                failed = self._request(
                    "POST",
                    f"/api/v1/render-agent/jobs/{job_id}/fail",
                    json={"code": "device_render_failed", "message": message[:2000]},
                )
                logger.info(
                    "device_task_failure_reported job_id=%s status=%s",
                    job_id,
                    failed.status_code,
                )
            except requests.RequestException:
                logger.exception("device_task_failure_report_failed job_id=%s", job_id)
            self._set_status(f"剪映导出失败：{message}")
