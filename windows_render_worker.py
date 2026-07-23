"""Windows-only worker that turns a draft_key into a Jianying-native MP4.

Legacy Mihe draft IDs are still accepted. The worker deliberately runs in the
logged-on desktop session because Jianying is a GUI application and cannot be
driven from a Session-0 Windows service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse

from desktop_bridge.core import (
    BridgeError,
    detect_draft_roots,
    detect_jianying_executables,
    extract_draft_key,
    import_draft_payload,
    launch_jianying,
    launch_mihe_sync_automated,
)


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.render-worker", override=True)

UUID_V4_RE = re.compile(
    r"(?i)(?<![0-9a-f])([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(?![0-9a-f])"
)


class RenderWorkerError(RuntimeError):
    """A render failure safe to expose to the trusted caller."""


class RenderWorkerBusy(RenderWorkerError):
    pass


def extract_render_draft_id(payload: Any) -> str:
    """Extract a Mihe UUID from the current render-service request shape."""
    if isinstance(payload, str):
        match = UUID_V4_RE.search(payload)
        if match:
            return match.group(1).lower()
        raw = payload.strip()
        if raw.startswith(("{", "[", '"')):
            try:
                return extract_render_draft_id(json.loads(raw))
            except json.JSONDecodeError:
                pass
        raise RenderWorkerError("没有找到有效的米核 draft_id（需要 UUID v4）")
    if isinstance(payload, list):
        for item in payload:
            try:
                return extract_render_draft_id(item)
            except RenderWorkerError:
                continue
        raise RenderWorkerError("草稿列表中没有有效的米核 draft_id")
    if isinstance(payload, dict):
        for key in ("draft_id", "drafts", "draft_url", "url", "output", "result", "data", "body"):
            value = payload.get(key)
            if value in (None, "", [], {}):
                continue
            try:
                return extract_render_draft_id(value)
            except RenderWorkerError:
                continue
        for value in payload.values():
            if not isinstance(value, (str, dict, list)):
                continue
            try:
                return extract_render_draft_id(value)
            except RenderWorkerError:
                continue
    raise RenderWorkerError("请求中没有有效的米核 draft_id")


def _path_from_env(name: str) -> Path | None:
    raw = (os.getenv(name) or "").strip().strip('"')
    return Path(raw).expanduser().resolve() if raw else None


@dataclass(frozen=True)
class WorkerConfig:
    api_token: str
    draft_root: Path | None
    jianying_exe: Path | None
    output_dir: Path
    public_base_url: str
    export_driver: str
    export_command: tuple[str, ...]
    mihe_timeout_seconds: int
    draft_timeout_seconds: int
    export_timeout_seconds: int
    dry_run: bool

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        draft_root = _path_from_env("WINDOWS_RENDER_DRAFT_ROOT")
        if draft_root is None:
            roots = detect_draft_roots()
            draft_root = roots[0] if roots else None

        jianying_exe = _path_from_env("WINDOWS_RENDER_JIANYING_EXE")
        if jianying_exe is None:
            executables = detect_jianying_executables()
            jianying_exe = executables[0] if executables else None

        output_dir = _path_from_env("WINDOWS_RENDER_OUTPUT_DIR")
        if output_dir is None:
            local = Path(os.getenv("LOCALAPPDATA") or Path.home())
            output_dir = (local / "DouyinRenderWorker" / "output").resolve()

        raw_command = (os.getenv("WINDOWS_RENDER_EXPORT_COMMAND_JSON") or "").strip()
        command: tuple[str, ...] = ()
        if raw_command:
            try:
                decoded = json.loads(raw_command)
            except json.JSONDecodeError as exc:
                raise RenderWorkerError("WINDOWS_RENDER_EXPORT_COMMAND_JSON 不是合法 JSON") from exc
            if not isinstance(decoded, list) or not decoded or not all(isinstance(item, str) and item for item in decoded):
                raise RenderWorkerError("WINDOWS_RENDER_EXPORT_COMMAND_JSON 必须是非空字符串数组")
            command = tuple(decoded)

        return cls(
            api_token=(os.getenv("WINDOWS_RENDER_API_TOKEN") or "").strip(),
            draft_root=draft_root,
            jianying_exe=jianying_exe,
            output_dir=output_dir,
            public_base_url=(os.getenv("WINDOWS_RENDER_PUBLIC_BASE_URL") or "http://127.0.0.1:8765").rstrip("/"),
            export_driver=(os.getenv("WINDOWS_RENDER_EXPORT_DRIVER") or "uiautomation").strip().lower(),
            export_command=command,
            mihe_timeout_seconds=max(10, int(os.getenv("WINDOWS_RENDER_MIHE_TIMEOUT_SECONDS") or 60)),
            draft_timeout_seconds=max(30, int(os.getenv("WINDOWS_RENDER_DRAFT_TIMEOUT_SECONDS") or 900)),
            export_timeout_seconds=max(60, int(os.getenv("WINDOWS_RENDER_EXPORT_TIMEOUT_SECONDS") or 1800)),
            dry_run=(os.getenv("WINDOWS_RENDER_DRY_RUN") or "").strip().lower() in {"1", "true", "yes"},
        )


class WindowsRenderPipeline:
    """Serialize Jianying jobs; one desktop can safely render one job."""

    def __init__(self, config: WorkerConfig):
        self.config = config
        self._render_lock = threading.Lock()
        self._active_job: dict[str, Any] | None = None
        self._last_job: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return {
            "status": "busy" if self._render_lock.locked() else "ready",
            "active_job": dict(self._active_job) if self._active_job else None,
            "last_job": dict(self._last_job) if self._last_job else None,
            "draft_root": str(self.config.draft_root) if self.config.draft_root else None,
            "jianying_exe": str(self.config.jianying_exe) if self.config.jianying_exe else None,
            "export_driver": self.config.export_driver,
            "dry_run": self.config.dry_run,
        }

    def render(self, request_payload: Any) -> dict[str, Any]:
        draft_key: dict[str, Any] | None = None
        if isinstance(request_payload, dict) and (
            isinstance(request_payload.get("calls"), list)
            or request_payload.get("draft_key") is not None
            or request_payload.get("key") is not None
        ):
            try:
                draft_key = extract_draft_key(request_payload)
            except BridgeError as exc:
                raise RenderWorkerError(str(exc)) from exc
        draft_id = None if draft_key is not None else extract_render_draft_id(request_payload)
        if not self._render_lock.acquire(blocking=False):
            raise RenderWorkerBusy("渲染机正在处理另一个视频；请稍后重试")
        started_at = time.time()
        supplied_job_id = request_payload.get("job_id") if isinstance(request_payload, dict) else None
        job_id = re.sub(r"[^A-Za-z0-9_-]", "", str(supplied_job_id or ""))[:80] or uuid.uuid4().hex
        self._active_job = {
            "job_id": job_id,
            "draft_id": draft_id,
            "source": "draft_key" if draft_key is not None else "mihe",
            "stage": "starting",
            "started_at": started_at,
        }
        try:
            result = self._render_locked(job_id, draft_id=draft_id, draft_key=draft_key)
            self._last_job = {
                "job_id": job_id,
                "draft_id": result["draft_id"],
                "status": "succeeded",
                "elapsed_seconds": round(time.time() - started_at, 2),
            }
            return result
        except Exception as exc:
            self._last_job = {
                "job_id": job_id,
                "draft_id": draft_id,
                "status": "failed",
                "error": str(exc),
                "elapsed_seconds": round(time.time() - started_at, 2),
            }
            raise
        finally:
            self._active_job = None
            self._render_lock.release()

    def _render_locked(
        self,
        job_id: str,
        *,
        draft_id: str | None,
        draft_key: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        if self.config.dry_run:
            resolved_draft_id = draft_id or hashlib.sha256(
                json.dumps(draft_key, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            draft_name = str(((draft_key or {}).get("draft") or {}).get("name") or resolved_draft_id)
            draft_dir = (self.config.draft_root or self.config.output_dir) / resolved_draft_id
            self._active_job["stage"] = "dry_run"
        else:
            if draft_key is not None:
                if self.config.draft_root is None:
                    raise RenderWorkerError("未配置或检测到剪映草稿目录 WINDOWS_RENDER_DRAFT_ROOT")
                self._active_job["stage"] = "importing_draft_key"
                report = import_draft_payload(draft_key, draft_root=self.config.draft_root)
                resolved_draft_id = str(report.get("draft_id") or "").strip()
                draft_name = str(report.get("draft_name") or resolved_draft_id).strip()
                draft_dir = Path(str(report.get("draft_dir") or "")).resolve()
                if not resolved_draft_id or not draft_dir.is_dir():
                    raise RenderWorkerError("draft_key 已执行，但没有生成有效剪映草稿")
            else:
                if not draft_id:
                    raise RenderWorkerError("请求中没有可渲染的草稿")
                resolved_draft_id = draft_id
                draft_name = draft_id
                draft_dir = self._sync_mihe_draft(draft_id)

        safe_draft_id = re.sub(r"[^A-Za-z0-9_-]", "", resolved_draft_id)[:80] or "draft"
        output_path = (self.config.output_dir / f"{job_id}-{safe_draft_id}.mp4").resolve()
        if self.config.output_dir not in output_path.parents:
            raise RenderWorkerError("输出路径越界")
        output_path.unlink(missing_ok=True)

        if self.config.dry_run:
            output_path.write_bytes(b"DouyinRenderWorker dry-run artifact\n")
        else:
            self._launch_jianying()
            self._export_draft(draft_name, draft_dir, output_path)
            self._wait_for_stable_file(output_path, self.config.export_timeout_seconds)

        self._active_job["draft_id"] = resolved_draft_id
        signature = self.sign_video_name(output_path.name)
        video_url = f"{self.config.public_base_url}/videos/{output_path.name}?signature={signature}"
        return {
            "status": "success",
            "job_id": job_id,
            "draft_id": resolved_draft_id,
            "video_url": video_url,
            "videos": [video_url],
            "output_path": str(output_path),
        }

    def _sync_mihe_draft(self, draft_id: str) -> Path:
        if self.config.draft_root is None:
            raise RenderWorkerError("未配置或检测到剪映草稿目录 WINDOWS_RENDER_DRAFT_ROOT")
        self.config.draft_root.mkdir(parents=True, exist_ok=True)
        self._active_job["stage"] = "mihe_sync"
        result = launch_mihe_sync_automated(draft_id, timeout_seconds=self.config.mihe_timeout_seconds)
        if result.get("status") != "submitted":
            raise RenderWorkerError(f"米核同步器未能无人值守提交：{result.get('status') or 'unknown'}")
        draft_dir = self.config.draft_root / draft_id
        content = draft_dir / "draft_content.json"
        deadline = time.time() + self.config.draft_timeout_seconds
        while time.time() < deadline:
            if content.is_file() and content.stat().st_size > 100:
                return draft_dir
            time.sleep(1)
        raise RenderWorkerError(f"等待米核草稿落盘超时：{draft_dir}")

    def _launch_jianying(self) -> None:
        if self.config.jianying_exe is None or not self.config.jianying_exe.is_file():
            raise RenderWorkerError("未配置或检测到 WINDOWS_RENDER_JIANYING_EXE")
        self._active_job["stage"] = "launching_jianying"
        launch_jianying(self.config.jianying_exe)
        time.sleep(8)

    def _export_draft(self, draft_name: str, draft_dir: Path, output_path: Path) -> None:
        self._active_job["stage"] = "exporting"
        driver = self.config.export_driver
        if driver == "pyjianyingdraft":
            try:
                from pyJianYingDraft import JianyingController
            except ImportError as exc:
                raise RenderWorkerError("缺少 pyJianYingDraft；请重新运行安装脚本并启用旧版导出驱动") from exc
            try:
                JianyingController().export_draft(
                    draft_name,
                    str(output_path),
                    timeout=self.config.export_timeout_seconds,
                )
            except Exception as exc:
                raise RenderWorkerError(f"剪映自动导出失败：{exc}") from exc
            return
        if driver == "command":
            if not self.config.export_command:
                raise RenderWorkerError("command 导出驱动缺少 WINDOWS_RENDER_EXPORT_COMMAND_JSON")
            replacements = {
                "{draft_name}": draft_name,
                "{draft_dir}": str(draft_dir),
                "{output_path}": str(output_path),
                "{jianying_exe}": str(self.config.jianying_exe or ""),
            }
            command = []
            for argument in self.config.export_command:
                expanded = argument
                for placeholder, value in replacements.items():
                    expanded = expanded.replace(placeholder, value)
                command.append(expanded)
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.config.export_timeout_seconds,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderWorkerError("剪映导出命令执行超时") from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "未知错误").strip()[-2000:]
                raise RenderWorkerError(f"剪映导出命令失败：{detail}")
            return
        if driver == "uiautomation":
            script = ROOT / "scripts" / "run_jianying_export_automation.ps1"
            if not script.is_file():
                raise RenderWorkerError(f"缺少剪映自动导出脚本：{script}")
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-DraftName",
                draft_name,
                "-OutputPath",
                str(output_path),
                "-JianyingExe",
                str(self.config.jianying_exe or ""),
                "-TimeoutSeconds",
                str(self.config.export_timeout_seconds),
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.config.export_timeout_seconds + 30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderWorkerError("剪映 UI 自动导出执行超时") from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "未知错误").strip()[-2000:]
                raise RenderWorkerError(f"剪映 UI 自动导出失败：{detail}")
            return
        raise RenderWorkerError(
            "剪映导出驱动尚未配置；请设置 WINDOWS_RENDER_EXPORT_DRIVER=uiautomation，"
            "或使用 WINDOWS_RENDER_EXPORT_DRIVER=command，"
            "或在剪映 6.x 测试机使用 pyjianyingdraft"
        )

    @staticmethod
    def _wait_for_stable_file(path: Path, timeout_seconds: int) -> None:
        deadline = time.time() + timeout_seconds
        previous_size = -1
        stable_samples = 0
        while time.time() < deadline:
            if path.is_file():
                size = path.stat().st_size
                if size > 0 and size == previous_size:
                    stable_samples += 1
                    if stable_samples >= 3:
                        return
                else:
                    stable_samples = 0
                previous_size = size
            time.sleep(1)
        raise RenderWorkerError(f"等待 MP4 文件生成超时：{path}")

    def sign_video_name(self, name: str) -> str:
        secret = self.config.api_token.encode("utf-8")
        return hmac.new(secret, name.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_video_signature(self, name: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign_video_name(name), signature)


config = WorkerConfig.from_env()
pipeline = WindowsRenderPipeline(config)
app = FastAPI(title="Windows 剪映渲染机", version="0.1.0")


def _authorize(authorization: str | None) -> None:
    if not config.api_token or config.api_token.lower().startswith("replace-"):
        raise HTTPException(status_code=503, detail="WINDOWS_RENDER_API_TOKEN 尚未配置")
    expected = f"Bearer {config.api_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="无效的渲染机访问令牌")


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    status = pipeline.status()
    status["configured"] = bool(
        config.dry_run
        or (
            config.draft_root
            and config.jianying_exe
            and config.export_driver in {"uiautomation", "command", "pyjianyingdraft"}
            and (config.export_driver != "command" or bool(config.export_command))
        )
    )
    return status


@app.post("/render")
def render(payload: Any = Body(default_factory=dict), authorization: str | None = Header(default=None)):
    _authorize(authorization)
    try:
        return pipeline.render(payload)
    except RenderWorkerBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (RenderWorkerError, BridgeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"渲染机内部错误：{exc}") from exc


@app.get("/videos/{file_name}")
def video(file_name: str, signature: str = Query(default="")):
    safe_name = Path(file_name).name
    if safe_name != file_name or not safe_name.lower().endswith(".mp4"):
        raise HTTPException(status_code=404, detail="视频不存在")
    if not pipeline.verify_video_signature(safe_name, signature):
        raise HTTPException(status_code=403, detail="视频签名无效")
    target = (config.output_dir / safe_name).resolve()
    if config.output_dir not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="视频不存在")
    return FileResponse(target, media_type="video/mp4", filename=safe_name)
