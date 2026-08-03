"""Daily, non-consuming health checks for the video generation pipeline."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from workflow_jobs import DATA_DIR

logger = logging.getLogger("workflow.health")
HEALTH_FILE = DATA_DIR / "health-checks.json"
_scheduler_started = False
_scheduler_lock = threading.Lock()


def _check(name: str, status: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "code": code,
        "message": message,
        "details": details,
    }


def run_health_check(trigger: str = "manual") -> dict[str, Any]:
    """Run checks that do not execute a paid workflow or consume provider quota."""
    checks: list[dict[str, Any]] = []
    coze_token = bool((os.getenv("COZE_API_TOKEN") or "").strip())
    workflow_ids = {
        key.removeprefix("COZE_WORKFLOW_"): value.strip()
        for key, value in os.environ.items()
        if key.startswith("COZE_WORKFLOW_") and value.strip()
    }
    if not coze_token:
        checks.append(_check("coze", "error", "coze_token_missing", "扣子 API Token 未配置"))
    elif not workflow_ids:
        checks.append(_check("coze", "error", "coze_workflow_missing", "扣子 Token 已配置，但没有工作流 ID"))
    else:
        checks.append(_check("coze", "ok", "coze_configured", "扣子 Token 与工作流 ID 已配置", workflow_count=len(workflow_ids), token_present=True))

    mihe_key = bool((os.getenv("MIHE_KEY") or os.getenv("MIHE_API_KEY") or "").strip())
    checks.append(_check("mihe", "ok" if mihe_key else "warning", "mihe_configured" if mihe_key else "mihe_key_missing", "米核密钥已配置" if mihe_key else "米核密钥未配置"))

    r2_enabled = (os.getenv("R2_EXPORT_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    r2_fields = all((os.getenv(name) or "").strip() for name in ("R2_EXPORT_UPLOAD_URL", "R2_EXPORT_PUBLIC_BASE_URL", "R2_EXPORT_UPLOAD_TOKEN"))
    checks.append(_check("r2", "ok" if r2_enabled and r2_fields else "warning", "r2_ready" if r2_enabled and r2_fields else "r2_not_ready", "R2 上传配置完整" if r2_enabled and r2_fields else "R2 未启用或上传配置不完整", enabled=r2_enabled, fields_complete=r2_fields))

    ffmpeg = shutil.which("ffmpeg")
    checks.append(_check("ffmpeg", "ok" if ffmpeg else "error", "ffmpeg_ready" if ffmpeg else "ffmpeg_missing", "FFmpeg 可用" if ffmpeg else "找不到 FFmpeg", path=ffmpeg or ""))

    try:
        disk = shutil.disk_usage(DATA_DIR)
        free_gb = disk.free / 1024 ** 3
        disk_status = "error" if free_gb < 2 else "warning" if free_gb < 10 else "ok"
        checks.append(_check("disk", disk_status, "disk_low" if disk_status != "ok" else "disk_ready", f"服务器可用磁盘 {free_gb:.1f} GB", free_bytes=disk.free, free_gb=round(free_gb, 2)))
    except OSError as exc:
        checks.append(_check("disk", "error", "disk_probe_failed", f"磁盘检查失败：{exc}"))

    coze_base = (os.getenv("COZE_API_BASE_URL") or "https://api.coze.cn").rstrip("/")
    try:
        response = requests.get(coze_base, timeout=8, allow_redirects=False)
        reachable = response.status_code < 500
        checks.append(_check("coze_network", "ok" if reachable else "error", "coze_reachable" if reachable else "coze_unreachable", f"扣子服务网络响应 HTTP {response.status_code}", http_status=response.status_code))
    except requests.RequestException as exc:
        checks.append(_check("coze_network", "error", "coze_network_failed", f"扣子服务无法连接：{exc.__class__.__name__}"))

    overall = "error" if any(item["status"] == "error" for item in checks) else "warning" if any(item["status"] == "warning" for item in checks) else "ok"
    snapshot = {"id": uuid.uuid4().hex, "trigger": trigger, "checked_at": time.time(), "overall": overall, "checks": checks}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    try:
        history = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        if not isinstance(history, list): history = []
    except (OSError, ValueError):
        pass
    history.insert(0, snapshot)
    HEALTH_FILE.write_text(json.dumps(history[:30], ensure_ascii=False, indent=2), encoding="utf-8")
    if overall != "ok":
        logger.warning("daily_health_check_warning trigger=%s overall=%s checks=%s", trigger, overall, json.dumps(checks, ensure_ascii=False, separators=(",", ":")))
    else:
        logger.info("daily_health_check_ok trigger=%s checks=%s", trigger, len(checks))
    return snapshot


def latest_health_check() -> dict[str, Any] | None:
    try:
        history = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        return history[0] if isinstance(history, list) and history else None
    except (OSError, ValueError, IndexError):
        return None


def _scheduler_loop() -> None:
    interval = max(3600, int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS") or 86400))
    while True:
        try:
            run_health_check("scheduled")
        except Exception:
            logger.exception("daily_health_check_failed")
        time.sleep(interval)


def start_health_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
        threading.Thread(target=_scheduler_loop, name="daily-health-check", daemon=True).start()

