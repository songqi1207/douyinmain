"""SQLite-backed workflow jobs, assets, and provider execution."""

from __future__ import annotations

import json
import logging
import logging.handlers
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from business_workflows import find_workflow_downloads
from workflow_registry import (
    LOCAL_CODES,
    REFERENCE_TEMPLATE_CODES,
    apply_workflow_input_defaults,
    get_workflow,
    published_workflow_id,
)


logger = logging.getLogger("workflow.jobs")
if not logger.handlers:
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(_log_handler)
logger.setLevel((os.getenv("WORKFLOW_LOG_LEVEL") or "INFO").upper())
logger.propagate = False


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("WORKFLOW_DATA_DIR") or ROOT / "temp" / "workflow_app").resolve()
LOG_DIR = Path(os.getenv("WORKFLOW_LOG_DIR") or DATA_DIR / "logs").resolve()

if not any(isinstance(handler, logging.handlers.RotatingFileHandler) for handler in logger.handlers):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _file_handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / "workflow.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        _file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(_file_handler)
    except OSError:
        logger.warning("workflow_log_file_unavailable dir=%s", LOG_DIR)
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
DB_PATH = Path(os.getenv("WORKFLOW_DB_PATH") or DATA_DIR / "workflow.sqlite3").resolve()
MAX_UPLOAD_BYTES = int(os.getenv("WORKFLOW_MAX_UPLOAD_BYTES") or 100 * 1024 * 1024)
DRAFT_KEY_RENDER_CODE = "DRAFT_KEY_EXPORT"
DRAFT_KEY_RENDER_CATEGORY = "剪映原生导出"
MAX_DRAFT_KEY_BYTES = int(os.getenv("WORKFLOW_MAX_DRAFT_KEY_BYTES") or 5 * 1024 * 1024)

ALLOWED_MIME_PREFIXES = ("image/", "video/", "audio/")
ALLOWED_DOCUMENT_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with _connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                workflow_code TEXT NOT NULL,
                category TEXT,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL,
                inputs_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                failed_stage TEXT,
                user_id TEXT,
                render_device_id TEXT,
                render_claimed_at REAL,
                cost_cents INTEGER NOT NULL DEFAULT 0,
                price_cents INTEGER NOT NULL DEFAULT 0,
                user_hidden_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
        if "render_device_id" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN render_device_id TEXT")
        if "render_claimed_at" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN render_claimed_at REAL")
        if "failed_stage" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN failed_stage TEXT")
        if "user_hidden_at" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN user_hidden_at REAL")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS job_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                message TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON job_logs (job_id, id)")
        db.commit()


def create_asset(original_name: str, mime_type: str, source, size_bytes: int) -> dict:
    if size_bytes <= 0:
        raise ValueError("上传文件为空")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件超过大小限制")
    supplied_mime = (mime_type or "").lower()
    guessed_mime = mimetypes.guess_type(original_name)[0]
    mime_type = (guessed_mime if supplied_mime in {"", "application/octet-stream"} else supplied_mime) or "application/octet-stream"
    if not mime_type.startswith(ALLOWED_MIME_PREFIXES) and mime_type not in ALLOWED_DOCUMENT_MIMES:
        raise ValueError("仅支持图片、视频、音频、DOCX 和 TXT 文件")

    asset_id = uuid.uuid4().hex
    suffix = Path(original_name or "asset").suffix.lower()[:12]
    stored_name = f"{asset_id}{suffix}"
    destination = UPLOAD_DIR / stored_name
    with destination.open("wb") as output:
        shutil.copyfileobj(source, output)
    actual_size = destination.stat().st_size
    if actual_size != size_bytes:
        size_bytes = actual_size
    with _connect() as db:
        db.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?)",
            (asset_id, Path(original_name or "asset").name, stored_name, mime_type, size_bytes, time.time()),
        )
        db.commit()
    return get_asset(asset_id)


def get_asset(asset_id: str) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    path = (UPLOAD_DIR / data["stored_name"]).resolve()
    if UPLOAD_DIR not in path.parents or not path.is_file():
        return None
    data["path"] = path
    return data


def create_job(
    workflow_code: str,
    category: str,
    inputs: dict,
    user_id: str | None = None,
    render_device_id: str | None = None,
    job_id: str | None = None,
    cost_points: int = 0,
    price_points: int = 0,
) -> dict:
    workflow = get_workflow(workflow_code, category)
    if not workflow:
        raise KeyError("workflow_not_found")
    if workflow["status"] != "online":
        raise PermissionError("workflow_not_online")
    inputs = apply_workflow_input_defaults(workflow_code, inputs)
    aliases = {
        "OWN01": "book_name",
        "OWN02": "cigarette_name",
        "OWN03": "god_name",
    }
    normalized_code = str(workflow_code or "").upper()
    alias = aliases.get(normalized_code)
    if alias and not str(inputs.get("theme") or "").strip():
        inputs["theme"] = inputs.get(alias)
    if normalized_code == "OWN01":
        inputs = _normalize_book_inputs(inputs, lookup_missing=False)
    validate_inputs(workflow, inputs)
    now = time.time()
    job_id = str(job_id or uuid.uuid4().hex)
    with _connect() as db:
        db.execute(
            """INSERT INTO jobs
            (id, workflow_code, category, status, stage, progress, inputs_json, results_json,
             error_code, error_message, user_id, render_device_id, render_claimed_at,
             cost_cents, price_cents, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', 'queued', 0, ?, '[]', NULL, NULL, ?, ?, NULL, ?, ?, ?, ?)""",
            (
                job_id,
                workflow_code.upper(),
                category,
                json.dumps(inputs, ensure_ascii=False),
                user_id,
                render_device_id,
                max(0, int(cost_points)),
                max(0, int(price_points)),
                now,
                now,
            ),
        )
        db.commit()
    append_job_log(job_id, "任务已创建，进入内容生成队列")
    return get_job(job_id)


def create_draft_key_render_job(
    payload: Any,
    user_id: str | None = None,
    render_device_id: str | None = None,
    job_id: str | None = None,
    cost_points: int = 0,
    price_points: int = 0,
) -> dict:
    """Create a normal background job for an already generated draft_key."""
    from desktop_bridge.core import BridgeError, extract_draft_key
    from utils.draft_key_importer import KeyValidationError, import_draft_key

    try:
        draft_key = extract_draft_key(payload)
        encoded = json.dumps(draft_key, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_DRAFT_KEY_BYTES:
            raise ValueError("draft_key 文件过大")
        import_draft_key(draft_key, dry_run=True)
    except BridgeError as exc:
        raise ValueError(str(exc)) from exc
    except KeyValidationError as exc:
        raise ValueError("draft_key 校验失败：" + "；".join(exc.errors)) from exc

    if not render_device_id and not (os.getenv("WORKFLOW_RENDER_API_URL") or "").strip():
        raise PermissionError("render_not_configured")

    now = time.time()
    job_id = str(job_id or uuid.uuid4().hex)
    inputs = {"draft_key": draft_key}
    with _connect() as db:
        db.execute(
            """INSERT INTO jobs
            (id, workflow_code, category, status, stage, progress, inputs_json, results_json,
             error_code, error_message, user_id, render_device_id, render_claimed_at,
             cost_cents, price_cents, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', 'queued', 0, ?, '[]', NULL, NULL, ?, ?, NULL, ?, ?, ?, ?)""",
            (
                job_id,
                DRAFT_KEY_RENDER_CODE,
                DRAFT_KEY_RENDER_CATEGORY,
                json.dumps(inputs, ensure_ascii=False),
                user_id,
                render_device_id,
                max(0, int(cost_points)),
                max(0, int(price_points)),
                now,
                now,
            ),
        )
        db.commit()
    append_job_log(job_id, "视频导出任务已创建，进入执行队列")
    return get_job(job_id)


def validate_inputs(workflow: dict, inputs: dict):
    for field in workflow.get("input_schema", []):
        name = field["name"]
        value = inputs.get(name)
        if field.get("required") and (value is None or value == "" or value == []):
            raise ValueError(f"missing:{name}")
        if field["type"] == "number" and value not in (None, ""):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"invalid_number:{name}")
            if field.get("min") is not None and value < field["min"]:
                raise ValueError(f"too_small:{name}")
            if field.get("max") is not None and value > field["max"]:
                raise ValueError(f"too_large:{name}")
        if field["type"] == "select" and value not in (None, ""):
            allowed_values = {option["value"] for option in field.get("options", [])}
            if allowed_values and value not in allowed_values:
                raise ValueError(f"invalid_option:{name}")
        if field["type"] in {"image", "video", "audio", "file"} and value:
            asset_ids = value if isinstance(value, list) else [value]
            if field.get("max_files") and len(asset_ids) > int(field["max_files"]):
                raise ValueError(f"too_many:{name}")
            for asset_id in asset_ids:
                asset = get_asset(str(asset_id))
                expected = field["type"]
                valid_type = bool(asset) and (
                    (expected == "file" and asset["mime_type"] in ALLOWED_DOCUMENT_MIMES)
                    or (expected != "file" and asset["mime_type"].startswith(f"{expected}/"))
                )
                if not valid_type:
                    raise ValueError(f"invalid_asset:{name}")


def get_job(job_id: str) -> dict | None:
    with _connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["inputs"] = json.loads(data.pop("inputs_json"))
    data["results"] = json.loads(data.pop("results_json"))
    return data


def get_result_path(filename: str) -> Path | None:
    if not filename or filename != Path(filename).name:
        return None
    path = (RESULT_DIR / filename).resolve()
    if RESULT_DIR not in path.parents or not path.is_file():
        return None
    return path


def user_can_access_result(user_id: str, filename: str, *, allow_all: bool = False) -> bool:
    """Allow access only to a completed result explicitly owned by the user."""
    if (
        not user_id
        or not filename
        or filename != Path(filename).name
        or Path(filename).suffix.lower() == ".json"
    ):
        return False
    expected_url = f"/api/v1/job-results/{filename}"
    with _connect() as db:
        if allow_all:
            rows = db.execute(
                """SELECT results_json FROM jobs
                   WHERE status = 'succeeded' AND instr(results_json, ?) > 0""",
                (filename,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT results_json FROM jobs
                   WHERE user_id = ? AND status = 'succeeded'
                     AND instr(results_json, ?) > 0""",
                (user_id, filename),
            ).fetchall()
    for row in rows:
        try:
            results = json.loads(row["results_json"])
        except (TypeError, ValueError):
            continue
        if any(
            isinstance(result, dict)
            and str(result.get("url") or "").split("?", 1)[0] == expected_url
            for result in results
        ):
            return True
    return False


def list_jobs(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    *,
    status: str = "",
    workflow_code: str = "",
) -> tuple[list[dict], int]:
    """Return newest jobs without exposing their submitted input payloads."""
    offset = (page - 1) * page_size
    # User-side deletion is a soft hide so administrators retain the audit trail.
    clauses = ["user_id = ?", "user_hidden_at IS NULL"]
    parameters: list[Any] = [user_id]
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status != "all":
        if normalized_status not in {"queued", "running", "rendering", "succeeded", "failed"}:
            raise ValueError("invalid_job_status")
        clauses.append("status = ?")
        parameters.append(normalized_status)
    normalized_code = str(workflow_code or "").strip().upper()
    if normalized_code:
        clauses.append("workflow_code = ?")
        parameters.append(normalized_code)
    where = " AND ".join(clauses)
    with _connect() as db:
        total = int(
            db.execute(
                f"SELECT COUNT(*) FROM jobs WHERE {where}",
                parameters,
            ).fetchone()[0]
        )
        rows = db.execute(
            f"""SELECT id FROM jobs WHERE {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (*parameters, page_size, offset),
        ).fetchall()
    return [job for row in rows if (job := get_job(row["id"]))], total


def list_admin_jobs(
    page: int = 1,
    page_size: int = 20,
    *,
    status: str = "",
    workflow_code: str = "",
    user_id: str = "",
    query: str = "",
    query_user_ids: list[str] | None = None,
) -> tuple[list[dict], int, dict[str, int]]:
    """Return cross-account jobs for the administrator console."""
    offset = (page - 1) * page_size
    clauses = ["1 = 1"]
    parameters: list[Any] = []
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status != "all":
        if normalized_status not in {"queued", "running", "rendering", "succeeded", "failed"}:
            raise ValueError("invalid_job_status")
        clauses.append("status = ?")
        parameters.append(normalized_status)
    normalized_code = str(workflow_code or "").strip().upper()
    if normalized_code:
        clauses.append("workflow_code = ?")
        parameters.append(normalized_code)
    normalized_user_id = str(user_id or "").strip()
    if normalized_user_id:
        clauses.append("user_id = ?")
        parameters.append(normalized_user_id)
    normalized_query = str(query or "").strip().lower()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        search_clauses = [
            "LOWER(id) LIKE ?",
            "LOWER(workflow_code) LIKE ?",
            "LOWER(COALESCE(category, '')) LIKE ?",
            "LOWER(inputs_json) LIKE ?",
        ]
        search_parameters: list[Any] = [pattern, pattern, pattern, pattern]
        matched_users = list(dict.fromkeys(str(value) for value in (query_user_ids or []) if str(value).strip()))
        if matched_users:
            placeholders = ",".join("?" for _ in matched_users)
            search_clauses.append(f"user_id IN ({placeholders})")
            search_parameters.extend(matched_users)
        clauses.append("(" + " OR ".join(search_clauses) + ")")
        parameters.extend(search_parameters)
    where = " AND ".join(clauses)
    with _connect() as db:
        summary_row = db.execute(
            f"""SELECT COUNT(*) AS total,
                       COUNT(DISTINCT user_id) AS users,
                       SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN status IN ('queued', 'running', 'rendering') THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN status = 'succeeded' THEN price_cents ELSE 0 END) AS points
                FROM jobs WHERE {where}""",
            parameters,
        ).fetchone()
        rows = db.execute(
            f"""SELECT id FROM jobs WHERE {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (*parameters, page_size, offset),
        ).fetchall()
        global_active = int(
            db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running', 'rendering')"
            ).fetchone()[0]
        )
    summary = {key: int(summary_row[key] or 0) for key in ("total", "users", "succeeded", "failed", "active", "points")}
    # The clear-queue control is global. Keep its count independent from the
    # administrator's current status/user/workflow/search filters.
    summary["global_active"] = global_active
    return [job for row in rows if (job := get_job(row["id"]))], summary["total"], summary


def clear_active_jobs() -> dict[str, Any]:
    """Delete every non-terminal job and refund any frozen user credits."""

    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT id FROM jobs WHERE status IN ('queued', 'running', 'rendering')"
        ).fetchall()
        job_ids = [str(row["id"]) for row in rows]
        if job_ids:
            placeholders = ",".join("?" for _ in job_ids)
            db.execute(
                f"DELETE FROM job_logs WHERE job_id IN ({placeholders})",
                job_ids,
            )
            db.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders})",
                job_ids,
            )
        db.commit()

    refunded = 0
    for job_id in job_ids:
        try:
            from site_accounts import settle_generation_reservation

            refunded += int(settle_generation_reservation(job_id, False))
        except Exception:
            logger.exception("admin_queue_refund_failed job_id=%s", job_id)

    redis_removed = 0
    if job_ids and (os.getenv("WORKFLOW_QUEUE_MODE") or "inline").strip().lower() == "redis":
        try:
            from redis import Redis
            from rq import Queue

            queue = Queue(
                "workflow-jobs",
                connection=Redis.from_url(os.getenv("REDIS_URL") or "redis://localhost:6379/0"),
            )
            redis_removed = int(queue.count)
            queue.empty()
        except Exception:
            logger.exception("admin_redis_queue_clear_failed")

    logger.warning(
        "admin_queue_cleared jobs=%s refunded=%s redis_removed=%s",
        len(job_ids),
        refunded,
        redis_removed,
    )
    return {
        "cleared": len(job_ids),
        "refunded": refunded,
        "redis_removed": redis_removed,
        "job_ids": job_ids,
    }


def job_summary() -> dict[str, int]:
    """Return persisted task counts for the public homepage summary."""
    with _connect() as db:
        rows = db.execute("SELECT status, COUNT(*) AS total FROM jobs GROUP BY status").fetchall()
    counts = {row["status"]: int(row["total"]) for row in rows}
    return {
        "total": sum(counts.values()),
        "succeeded": counts.get("succeeded", 0),
        "active": counts.get("queued", 0) + counts.get("running", 0) + counts.get("rendering", 0),
        "failed": counts.get("failed", 0),
    }


def workflow_job_counts(workflow_codes: list[str]) -> dict[str, int]:
    codes = list(dict.fromkeys(str(code or "").upper() for code in workflow_codes if str(code or "").strip()))
    if not codes:
        return {}
    placeholders = ",".join("?" for _ in codes)
    with _connect() as db:
        rows = db.execute(
            f"SELECT workflow_code, COUNT(*) AS total FROM jobs WHERE workflow_code IN ({placeholders}) GROUP BY workflow_code",
            codes,
        ).fetchall()
    return {row["workflow_code"]: int(row["total"]) for row in rows}


def _update_job(job_id: str, **changes):
    allowed = {
        "status",
        "stage",
        "progress",
        "inputs_json",
        "results_json",
        "error_code",
        "error_message",
        "render_claimed_at",
        "cost_cents",
        "price_cents",
    }
    values = {key: value for key, value in changes.items() if key in allowed}
    with _connect() as db:
        if values.get("status") == "failed" and values.get("stage") == "failed":
            previous = db.execute("SELECT stage, failed_stage FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if previous:
                values["failed_stage"] = previous["failed_stage"] or previous["stage"] or "failed"
        values["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in values)
        db.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*values.values(), job_id))
        db.commit()
    terminal_status = values.get("status")
    if terminal_status in {"succeeded", "failed"}:
        try:
            from site_accounts import settle_generation_reservation

            settle_generation_reservation(job_id, terminal_status == "succeeded")
        except Exception:
            logger.exception("job_quota_settlement_failed job_id=%s status=%s", job_id, terminal_status)
    if {"status", "stage", "progress"} & values.keys():
        logger.info(
            "job_state job_id=%s status=%s stage=%s progress=%s",
            job_id,
            values.get("status", "-"),
            values.get("stage", "-"),
            values.get("progress", "-"),
        )


def _public_job_message(message: str) -> str:
    """Convert provider/internal wording into customer-facing job progress text."""
    text = " ".join(str(message or "").split())
    text = re.sub(r"workflow_id=[^，）\s]+", "生成任务", text)
    text = re.sub(r"（HTTP\s*\d+[^）]*）", "", text, flags=re.IGNORECASE)
    text = re.sub(r"HTTP\s*\d+", "服务响应", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z0-9_])draft_key(?![A-Za-z0-9_])", "视频草稿", text)
    replacements = (
        ("扣子已发布工作流", "内容生成服务"),
        ("扣子工作流", "内容生成服务"),
        ("扣子服务", "内容生成服务"),
        ("扣子内容", "内容"),
        ("扣子", "内容生成服务"),
        ("Coze", "内容生成服务"),
        ("coze", "内容生成服务"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return text[:2000]


def _public_coze_node_title(node_title: str) -> str:
    title = _public_job_message(node_title).strip()
    if not title or title in {"-", "End", "end", "结束"}:
        return ""
    return title[:80]


def append_job_log(job_id: str, message: str, level: str = "info") -> None:
    """Persist a user-visible per-job log line; never break the job on failure."""
    text = _public_job_message(message)
    if not text:
        return
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO job_logs (job_id, level, message, created_at)
                   SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM jobs WHERE id = ?)""",
                (job_id, level, text, time.time(), job_id),
            )
            db.commit()
    except sqlite3.Error:
        logger.exception("job_log_write_failed job_id=%s", job_id)


def get_job_logs(job_id: str, after_id: int = 0, limit: int = 500) -> list[dict]:
    with _connect() as db:
        rows = db.execute(
            """SELECT id, level, message, created_at FROM job_logs
               WHERE job_id = ? AND id > ? ORDER BY id LIMIT ?""",
            (job_id, max(0, int(after_id)), max(1, min(int(limit), 1000))),
        ).fetchall()
    return [dict(row) for row in rows]


def enqueue_job(job_id: str, background_tasks=None):
    mode = (os.getenv("WORKFLOW_QUEUE_MODE") or "inline").strip().lower()
    logger.info("job_enqueue job_id=%s queue_mode=%s", job_id, mode)
    if mode == "redis":
        from redis import Redis
        from rq import Queue

        connection = Redis.from_url(os.getenv("REDIS_URL") or "redis://localhost:6379/0")
        Queue("workflow-jobs", connection=connection).enqueue(execute_job, job_id, job_timeout=1800)
    elif background_tasks is not None:
        background_tasks.add_task(execute_job, job_id)
    else:
        execute_job(job_id)


def execute_job(job_id: str):
    job = get_job(job_id)
    if not job:
        logger.warning("job_missing job_id=%s", job_id)
        return
    started_at = time.monotonic()
    try:
        _update_job(job_id, status="running", stage="preparing", progress=10)
        if job["workflow_code"] == "OWN01":
            resolved_inputs = _normalize_book_inputs(job["inputs"], lookup_missing=True)
            if resolved_inputs != job["inputs"]:
                _update_job(job_id, inputs_json=json.dumps(resolved_inputs, ensure_ascii=False))
                job = {**job, "inputs": resolved_inputs}
                resolved_author = str(resolved_inputs.get("author") or "").strip()
                if resolved_author and not _book_author_is_placeholder(resolved_author):
                    append_job_log(job_id, f"已识别书籍作者：{resolved_author}")
        mode = (os.getenv("WORKFLOW_PROVIDER_MODE") or "demo").strip().lower()
        build_mode = (os.getenv("WORKFLOW_BUILD_MODE") or "template").strip().lower()
        logger.info(
            "job_started job_id=%s workflow=%s category=%s provider_mode=%s build_mode=%s",
            job_id,
            job["workflow_code"],
            job["category"],
            mode,
            build_mode,
        )
        published_local = (
            job["workflow_code"] in LOCAL_CODES
            and bool((os.getenv("COZE_API_TOKEN") or "").strip())
            and bool(published_workflow_id(job["workflow_code"]))
        )
        append_job_log(job_id, "开始准备创作素材与生成环境")
        if job["workflow_code"] == DRAFT_KEY_RENDER_CODE:
            logger.info("job_path job_id=%s path=draft_key_import", job_id)
            append_job_log(job_id, "执行方式：导入已有视频草稿")
            results = _save_draft_key_result(job, job["inputs"])
        elif published_local:
            logger.info("job_path job_id=%s path=coze_published", job_id)
            append_job_log(job_id, "执行方式：生成文案、分镜与视频草稿")
            results = _run_coze(job)
        elif job["workflow_code"] in LOCAL_CODES:
            logger.info("job_path job_id=%s path=local_workflow", job_id)
            append_job_log(job_id, "执行方式：本地生成文案、分镜与视频草稿")
            results = _run_local_workflow(job)
        elif job["workflow_code"] in REFERENCE_TEMPLATE_CODES and build_mode == "template":
            logger.info("job_path job_id=%s path=reference_template", job_id)
            append_job_log(job_id, "执行方式：参考模板生成视频草稿")
            results = _run_reference_template(job)
        elif mode == "coze":
            logger.info("job_path job_id=%s path=coze_provider", job_id)
            append_job_log(job_id, "执行方式：生成文案、分镜与视频草稿")
            results = _run_coze(job)
        else:
            logger.info("job_path job_id=%s path=demo", job_id)
            append_job_log(job_id, "执行方式：演示模式生成")
            results = _run_demo(job)
        workflow = get_workflow(job["workflow_code"], job["category"]) or {}
        if any(result["type"] == "draft" for result in results):
            if job.get("render_device_id"):
                logger.info(
                    "job_render_route job_id=%s route=device device_id=%s",
                    job_id,
                    job["render_device_id"],
                )
                _queue_device_render(job, results)
                return
            logger.info("job_render_route job_id=%s route=server", job_id)
            results = _render_drafts(job, results)
        cost_cents = int(job.get("cost_cents") or os.getenv(f"WORKFLOW_COST_CENTS_{job['workflow_code']}") or 0)
        price_cents = int(job.get("price_cents") or os.getenv(f"WORKFLOW_PRICE_CENTS_{job['workflow_code']}") or 0)
        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            progress=100,
            results_json=json.dumps(results, ensure_ascii=False),
            cost_cents=cost_cents,
            price_cents=price_cents,
        )
        logger.info(
            "job_completed job_id=%s workflow=%s elapsed_seconds=%.3f",
            job_id,
            job["workflow_code"],
            time.monotonic() - started_at,
        )
        append_job_log(job_id, f"任务完成，总耗时 {time.monotonic() - started_at:.1f} 秒")
    except ProviderError as exc:
        public_error = _public_job_message(str(exc))
        _update_job(job_id, status="failed", stage="failed", progress=100, error_code=exc.code, error_message=public_error)
        logger.warning(
            "job_failed job_id=%s workflow=%s code=%s message=%r elapsed_seconds=%.3f",
            job_id,
            job["workflow_code"],
            exc.code,
            str(exc),
            time.monotonic() - started_at,
        )
        append_job_log(job_id, f"任务失败：{public_error}", level="error")
    except Exception as exc:
        _update_job(job_id, status="failed", stage="failed", progress=100, error_code="internal_error", error_message=str(exc))
        logger.exception(
            "job_failed job_id=%s workflow=%s code=internal_error elapsed_seconds=%.3f",
            job_id,
            job["workflow_code"],
            time.monotonic() - started_at,
        )
        append_job_log(job_id, f"任务失败：内部错误（{exc}）", level="error")


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_retryable_book_provider_error(exc: ProviderError) -> bool:
    message = str(exc)
    return (
        exc.code == "provider_error"
        and "sandbox" in message.lower()
        and "end" in message
    )


def _asset_public_url(asset_id: str) -> str:
    base = (os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/v1/assets/{asset_id}"


def _visible_text_has_encoding_damage(value: str) -> bool:
    compact = "".join(character for character in str(value or "") if not character.isspace())
    return bool(
        compact
        and (
            all(character in {"?", "\ufffd"} for character in compact)
            or "\ufffd" in compact
            or re.search(r"\?{3,}", compact)
        )
    )


def _configured_visible_text(env_name: str, default: str) -> str:
    """Return configured visible text unless encoding replacement destroyed it."""
    value = (os.getenv(env_name) or "").strip()
    if not value or _visible_text_has_encoding_damage(value):
        if value:
            logger.warning(
                "visible_text_config_encoding_invalid env=%s fallback_used=true",
                env_name,
            )
        return default
    return value


_BOOK_AUTHOR_PLACEHOLDERS = {"", "佚名", "未知", "未知作者", "unknown", "anonymous"}
_DOUBAN_BOOK_SUGGEST_URL = "https://book.douban.com/j/subject_suggest"
_WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"


def _book_author_is_placeholder(value: str) -> bool:
    return str(value or "").strip().casefold() in _BOOK_AUTHOR_PLACEHOLDERS


def _normalize_book_author(value: str) -> str:
    """Keep the author name only; the workflow caption adds its own 著 suffix."""

    author = str(value or "").strip()
    return re.sub(r"(?:\s*(?:作者\s*)?著)+\s*$", "", author).strip()


def _split_book_theme(value: str) -> tuple[str, str]:
    subject = str(value or "").strip()
    for separator in ("｜", "|"):
        if separator in subject:
            title, author = (part.strip() for part in subject.split(separator, 1))
            return title or subject, author
    return subject, ""


def _normalized_book_title(value: str) -> str:
    return re.sub(r"[\s《》〈〉「」『』·:：,，。.!！?？'\"]+", "", str(value or "")).casefold()


def _wikidata_entity_id(claim: dict[str, Any]) -> str:
    value = (
        (claim.get("mainsnak") or {})
        .get("datavalue", {})
        .get("value", {})
    )
    return str(value.get("id") or "") if isinstance(value, dict) else ""


def _douban_suggestion_author(title: str, payload: Any) -> str:
    normalized_title = _normalized_book_title(title)
    if not normalized_title or not isinstance(payload, list):
        return ""
    for item in payload:
        if (
            not isinstance(item, dict)
            or str(item.get("type") or "").lower() != "b"
            or _normalized_book_title(item.get("title")) != normalized_title
        ):
            continue
        author = str(item.get("author_name") or "").strip()
        author = re.sub(r"^(?:\[[^\]]{1,8}\]\s*)+", "", author).strip()
        if author:
            return author
    return ""


@lru_cache(maxsize=256)
def _lookup_book_author(title: str) -> str:
    """Look up a book author through Wikidata; return empty on uncertainty."""
    normalized_title = _normalized_book_title(title)
    if not normalized_title:
        return ""
    headers = {
        "User-Agent": "AI-Video-Creator/1.0 (+https://api.songqi.online/)",
        "Accept": "application/json",
    }
    session = requests.Session()
    session.trust_env = False
    try:
        douban_response = session.get(
            _DOUBAN_BOOK_SUGGEST_URL,
            params={"q": title},
            headers={**headers, "Referer": "https://book.douban.com/"},
            timeout=(3, 6),
        )
        douban_response.raise_for_status()
        douban_author = _douban_suggestion_author(title, douban_response.json())
        if douban_author:
            return douban_author
    except (requests.RequestException, TypeError, ValueError):
        logger.info("douban_book_author_lookup_unavailable title=%r", title)
    try:
        search_response = session.get(
            _WIKIDATA_API_URL,
            params={
                "action": "wbsearchentities",
                "search": title,
                "language": "zh",
                "uselang": "zh",
                "format": "json",
                "limit": 8,
            },
            headers=headers,
            timeout=(3, 6),
        )
        search_response.raise_for_status()
        candidates = [
            item
            for item in (search_response.json().get("search") or [])
            if isinstance(item, dict)
            and _normalized_book_title(item.get("label") or (item.get("match") or {}).get("text"))
            == normalized_title
            and str(item.get("id") or "").startswith("Q")
        ]
        candidate_ids = [str(item["id"]) for item in candidates[:6]]
        if not candidate_ids:
            return ""
        entity_response = session.get(
            _WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(candidate_ids),
                "props": "claims",
                "format": "json",
            },
            headers=headers,
            timeout=(3, 6),
        )
        entity_response.raise_for_status()
        entities = entity_response.json().get("entities") or {}
        author_ids: list[str] = []
        for candidate_id in candidate_ids:
            claims = (entities.get(candidate_id) or {}).get("claims") or {}
            author_ids = [
                entity_id
                for entity_id in (_wikidata_entity_id(item) for item in claims.get("P50") or [])
                if entity_id
            ]
            if author_ids:
                break
        if not author_ids:
            return ""
        author_response = session.get(
            _WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "ids": "|".join(author_ids[:3]),
                "props": "labels",
                "languages": "zh-cn|zh-hans|zh|en",
                "format": "json",
            },
            headers=headers,
            timeout=(3, 6),
        )
        author_response.raise_for_status()
        author_entities = author_response.json().get("entities") or {}
        names: list[str] = []
        for author_id in author_ids[:3]:
            labels = (author_entities.get(author_id) or {}).get("labels") or {}
            name = str(
                (
                    labels.get("zh-cn")
                    or labels.get("zh-hans")
                    or labels.get("zh")
                    or labels.get("en")
                    or {}
                ).get("value")
                or ""
            ).strip()
            if name and name not in names:
                names.append(name)
        return "、".join(names)
    except (requests.RequestException, TypeError, ValueError, AttributeError):
        logger.warning("book_author_lookup_failed title=%r", title, exc_info=True)
        return ""


def _normalize_book_inputs(inputs: dict[str, Any], *, lookup_missing: bool) -> dict[str, Any]:
    result = dict(inputs)
    raw_theme = str(result.get("theme") or result.get("book_name") or "").strip()
    subject, inline_author = _split_book_theme(raw_theme)
    current_author = str(result.get("author") or "").strip()
    if inline_author:
        current_author = inline_author
    elif lookup_missing and _book_author_is_placeholder(current_author):
        current_author = _lookup_book_author(subject) or current_author
    current_author = _normalize_book_author(current_author)
    result["theme"] = subject
    if current_author:
        result["author"] = current_author
    return result


def _provider_inputs(inputs: dict, workflow_code: str = "") -> dict:
    result: dict[str, Any] = {}
    for key, value in inputs.items():
        values = value if isinstance(value, list) else [value]
        if values and all(get_asset(str(item)) for item in values):
            urls = [_asset_public_url(str(item)) for item in values]
            result[key] = urls if isinstance(value, list) else urls[0]
        else:
            result[key] = value

    code = str(workflow_code or "").upper()
    result.pop("voice_notice", None)
    if code == "OWN01":
        result = _normalize_book_inputs(result, lookup_missing=True)
        subject = str(result.pop("theme", "") or result.pop("book_name", "") or "").strip()
        author = str(result.pop("author", "") or "").strip()
        author = _normalize_book_author(
            author or _configured_visible_text("BOOK_DEFAULT_AUTHOR", "佚名")
        )
        try:
            image_count = max(
                2,
                min(
                    int(
                        result.pop("scene_count", "")
                        or result.pop("img_count", "")
                        or os.getenv("BOOK_DEFAULT_IMAGE_COUNT")
                        or 10
                    ),
                    30,
                ),
            )
        except (TypeError, ValueError):
            image_count = 2
        result = {
            # Two spaces intentionally keep the original workflow's invisible
            # watermark caption alive. Do not strip this value.
            "account_name": "  ",
            "author": author,
            "img_count": str(image_count),
            "subject": subject,
            "yinse": str(
                result.pop("voice_id", "")
                or result.pop("yinse", "")
                or os.getenv("BOOK_DEFAULT_VOICE_ID")
                or "7620288417930297386"
            ).strip(),
        }
    elif code == "OWN02":
        theme = str(
            result.pop("theme", "") or result.pop("cigarette_name", "") or ""
        ).strip()
        result = {
            "left": str(result.pop("left", "") or "").strip()
            or _configured_visible_text("CIGARETTE_LEFT_TEXT", "未成年人禁止吸烟"),
            "left_top": str(result.pop("left_top", "") or "").strip()
            or _configured_visible_text("CIGARETTE_LEFT_TOP_TEXT", "吸烟有害身体健康"),
            "xiangyan_name": theme,
        }
    elif code == "OWN03":
        from workflows.god.provider import build_god_provider_parameters

        result = build_god_provider_parameters(result)
    elif code == "G259":
        title = str(result.pop("theme", "") or result.pop("title", "") or "").strip()
        mode = result.pop("content_mode", "human_insight")
        if mode == "life_story" and title and "一生" not in title:
            title = f"{title}的一生"
        result["biaoti"] = title
    elif code == "G258":
        result["biaoti"] = result.pop("theme", "") or result.pop("title", "")
    elif code == "G168":
        result["text"] = result.pop("theme", "") or result.pop("novel_document", "")
        result.pop("opening_title", None)
    elif code == "G45":
        result["author"] = result.pop("ip_name", "")
        result["content"] = result.pop("text", "")
        result["title"] = result.pop("theme", "") or result.get("title", "")
    elif code == "G263":
        theme = result.pop("theme", "")
        result["subject"] = theme
        result["name"] = theme
    elif code == "G159":
        result["title"] = result.pop("theme", "") or result.get("title", "")
    elif code == "G222":
        theme = result.pop("theme", "")
        result["business"] = theme
        result["kaichang"] = f"{theme}，它的商业模式到底是什么？"
    secret_bindings = {
        "api_key": "SUTUI_API_KEY",
        "APIkey": "SUTUI_API_KEY",
        "api_token": "SUTUI_API_KEY",
        "st_api_key": "SUTUI_API_KEY",
        "hs_api_key": "VOLCENGINE_API_KEY",
        "mihe_key": "MIHE_KEY",
        "feishu_url": "FEISHU_ASSET_URL",
    }
    for parameter, env_name in secret_bindings.items():
        if code == "OWN02" and parameter == "mihe_key":
            continue
        if os.getenv(env_name):
            result[parameter] = os.getenv(env_name)
    return result


def _post_coze_workflow(
    url: str,
    *,
    headers: dict,
    payload: dict,
    job_id: str = "-",
    workflow_code: str = "-",
):
    """Call Coze directly unless environment proxy use is explicitly enabled."""
    connect_timeout = max(1, int(os.getenv("COZE_CONNECT_TIMEOUT_SECONDS") or 45))
    read_timeout = max(1, int(os.getenv("COZE_WORKFLOW_TIMEOUT_SECONDS") or 900))
    connect_attempts = max(1, int(os.getenv("COZE_CONNECT_ATTEMPTS") or 3))
    request_kwargs = {
        "headers": headers,
        "json": payload,
        "stream": True,
        "timeout": (connect_timeout, read_timeout),
    }
    use_env_proxy = (os.getenv("COZE_USE_ENV_PROXY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    started_at = time.monotonic()

    def record_usage(status: str, *, response_status: int | None = None, error_code: str = "", error_message: str = "") -> None:
        if job_id == "-":
            return
        try:
            from site_accounts import record_provider_usage_event, workflow_pricing_snapshot

            pricing = workflow_pricing_snapshot(workflow_code)
            elapsed_ms = round((time.monotonic() - started_at) * 1000)
            record_provider_usage_event(
                job_id=job_id,
                workflow_code=workflow_code,
                provider="coze",
                status=status,
                estimated_points=pricing["coze_cost_points"],
                http_status=response_status,
                elapsed_ms=elapsed_ms,
                error_code=error_code,
                error_message=error_message,
            )
            if pricing["mihe_cost_points"] > 0:
                record_provider_usage_event(
                    job_id=job_id,
                    workflow_code=workflow_code,
                    provider="mihe",
                    status=status,
                    estimated_points=pricing["mihe_cost_points"],
                    http_status=response_status,
                    elapsed_ms=elapsed_ms,
                    error_code=error_code,
                    error_message=error_message,
                )
        except Exception:
            logger.exception("provider_usage_record_failed job_id=%s workflow=%s", job_id, workflow_code)

    logger.info(
        "coze_request_started job_id=%s workflow=%s transport=%s connect_timeout=%s read_timeout=%s connect_attempts=%s",
        job_id,
        workflow_code,
        "system_proxy" if use_env_proxy else "direct",
        connect_timeout,
        read_timeout,
        connect_attempts,
    )
    if job_id != "-":
        append_job_log(
            job_id,
            f"正在生成文案与分镜，最长等待 {read_timeout} 秒",
        )
    if use_env_proxy:
        try:
            response = requests.post(url, **request_kwargs)
            record_usage(
                "success" if response.status_code < 400 else "error",
                response_status=response.status_code,
                error_code="http_error" if response.status_code >= 400 else "",
                error_message=f"HTTP {response.status_code}" if response.status_code >= 400 else "",
            )
            logger.info(
                "coze_request_finished job_id=%s workflow=%s transport=system_proxy status=%s elapsed_seconds=%.3f",
                job_id,
                workflow_code,
                response.status_code,
                time.monotonic() - started_at,
            )
            return response
        except requests.exceptions.ProxyError:
            logger.warning(
                "coze_proxy_failed job_id=%s workflow=%s fallback=direct",
                job_id,
                workflow_code,
            )

    direct_session = requests.Session()
    direct_session.trust_env = False
    try:
        for attempt in range(1, connect_attempts + 1):
            try:
                response = direct_session.post(url, **request_kwargs)
                record_usage(
                    "success" if response.status_code < 400 else "error",
                    response_status=response.status_code,
                    error_code="http_error" if response.status_code >= 400 else "",
                    error_message=f"HTTP {response.status_code}" if response.status_code >= 400 else "",
                )
                logger.info(
                    "coze_request_finished job_id=%s workflow=%s transport=direct status=%s attempt=%s elapsed_seconds=%.3f",
                    job_id,
                    workflow_code,
                    response.status_code,
                    attempt,
                    time.monotonic() - started_at,
                )
                if job_id != "-":
                    append_job_log(
                        job_id,
                        f"内容生成服务已开始返回结果，耗时 {time.monotonic() - started_at:.1f} 秒",
                    )
                return response
            except requests.exceptions.ConnectTimeout as exc:
                logger.warning(
                    "coze_connect_timeout job_id=%s workflow=%s attempt=%s/%s elapsed_seconds=%.3f",
                    job_id,
                    workflow_code,
                    attempt,
                    connect_attempts,
                    time.monotonic() - started_at,
                )
                if attempt < connect_attempts:
                    if job_id != "-":
                        append_job_log(
                            job_id,
                            f"第 {attempt} 次连接内容生成服务超时，正在自动重试"
                            f"（还可重试 {connect_attempts - attempt} 次）",
                            level="warning",
                        )
                    continue
                if job_id != "-":
                    append_job_log(
                        job_id,
                        f"内容生成服务连接超时（每次 {connect_timeout} 秒，已尝试 {connect_attempts} 次）",
                        level="error",
                    )
                record_usage("timeout", error_code="provider_timeout", error_message="connect timeout")
                raise ProviderError(
                    "provider_timeout",
                    f"内容生成服务连接超时，已自动尝试 {connect_attempts} 次，请稍后重试",
                ) from exc
    except requests.exceptions.Timeout as exc:
        record_usage("timeout", error_code="provider_timeout", error_message="request timeout")
        logger.warning(
            "coze_request_timeout job_id=%s workflow=%s elapsed_seconds=%.3f",
            job_id,
            workflow_code,
            time.monotonic() - started_at,
        )
        if job_id != "-":
            append_job_log(
                job_id,
                f"内容生成超时（已等待 {time.monotonic() - started_at:.1f} 秒）",
                level="error",
            )
        raise ProviderError("provider_timeout", "内容生成超时，请稍后重试") from exc
    except requests.exceptions.RequestException as exc:
        record_usage("error", error_code="provider_unavailable", error_message=type(exc).__name__)
        logger.warning(
            "coze_request_failed job_id=%s workflow=%s exception=%s elapsed_seconds=%.3f",
            job_id,
            workflow_code,
            type(exc).__name__,
            time.monotonic() - started_at,
        )
        if job_id != "-":
            append_job_log(job_id, f"无法连接内容生成服务（{type(exc).__name__}）", level="error")
        raise ProviderError("provider_unavailable", "无法连接内容生成服务，请检查服务器网络") from exc
    finally:
        direct_session.close()


def _read_coze_stream(response, *, job_id: str, workflow_code: str) -> Any:
    event_name = ""
    final_data: Any = None
    started_nodes: set = set()
    finished_nodes: set = set()
    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        line = line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        raw_data = line[5:].strip()
        try:
            event_data = json.loads(raw_data)
        except (TypeError, ValueError):
            logger.warning(
                "coze_stream_invalid_event job_id=%s workflow=%s event=%s bytes=%s",
                job_id,
                workflow_code,
                event_name or "-",
                len(raw_data.encode("utf-8")),
            )
            continue
        if not isinstance(event_data, dict):
            continue

        node_title = " ".join(str(event_data.get("node_title") or "-").split())[:80]
        logger.info(
            "coze_stream_event job_id=%s workflow=%s event=%s node_id=%s node_title=%s node_finished=%s content_type=%s",
            job_id,
            workflow_code,
            event_name or "-",
            event_data.get("node_id") or "-",
            node_title,
            event_data.get("node_is_finish", "-"),
            event_data.get("content_type") or "-",
        )
        node_key = str(event_data.get("node_id") or node_title)
        public_node_title = _public_coze_node_title(node_title)
        if public_node_title and node_key not in started_nodes:
            started_nodes.add(node_key)
            append_job_log(job_id, f"生成步骤开始：{public_node_title}")
        if (
            public_node_title
            and event_data.get("node_is_finish")
            and node_key not in finished_nodes
        ):
            finished_nodes.add(node_key)
            append_job_log(job_id, f"生成步骤完成：{public_node_title}")
            _update_job(job_id, progress=min(70, 35 + 5 * len(finished_nodes)))
        normalized_event = event_name.strip().lower()
        code = event_data.get("code")
        if normalized_event in {"error", "failed"} or code not in (None, 0):
            message = str(
                event_data.get("msg")
                or event_data.get("message")
                or event_data.get("error_message")
                or "内容生成失败"
            )
            append_job_log(job_id, f"内容生成返回错误：{message}", level="error")
            raise ProviderError("provider_error", message)
        if normalized_event == "message" and "content" in event_data:
            final_data = _decode_nested_json(event_data["content"])
        if normalized_event in {"done", "finish", "completed"}:
            break

    if final_data is None:
        append_job_log(job_id, "内容生成结束，但没有拿到最终结果", level="error")
        raise ProviderError("empty_result", "内容生成完成但没有返回结果")
    append_job_log(job_id, "内容生成完成，正在整理视频草稿")
    return final_data


def _run_coze(job: dict) -> list[dict]:
    token = (os.getenv("COZE_API_TOKEN") or "").strip()
    workflow_id = published_workflow_id(job["workflow_code"])
    if not token or not workflow_id:
        raise ProviderError("provider_not_configured", "内容生成服务尚未配置完成")
    _update_job(job["id"], stage="generating", progress=35)
    draft_attempts = (
        max(1, int(os.getenv("COZE_INCOMPLETE_DRAFT_ATTEMPTS") or 2))
        if job["workflow_code"] in LOCAL_CODES
        else 1
    )
    provider_parameters = _provider_inputs(job["inputs"], job["workflow_code"])
    for draft_attempt in range(1, draft_attempts + 1):
        attempt_parameters = dict(provider_parameters)
        if job["workflow_code"] == "OWN01" and draft_attempt > 1:
            try:
                current_count = int(str(attempt_parameters.get("img_count") or "0"))
                fallback_count = max(2, int(os.getenv("BOOK_FALLBACK_IMAGE_COUNT") or 10))
            except (TypeError, ValueError):
                current_count = 0
                fallback_count = 10
            if current_count > fallback_count:
                attempt_parameters["img_count"] = str(fallback_count)
                append_job_log(
                    job["id"],
                    "高分镜生成不稳定，正在使用稳定分镜数重新生成",
                    level="warning",
                )
        attempt_suffix = (
            f"，草稿生成第 {draft_attempt}/{draft_attempts} 次"
            if draft_attempts > 1
            else ""
        )
        append_job_log(
            job["id"],
            f"开始生成文案、分镜与视频草稿{attempt_suffix}",
        )
        response = _post_coze_workflow(
            (os.getenv("COZE_API_BASE_URL") or "https://api.coze.cn").rstrip("/") + "/v1/workflow/stream_run",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            payload={"workflow_id": workflow_id, "parameters": attempt_parameters},
            job_id=job["id"],
            workflow_code=job["workflow_code"],
        )
        try:
            if response.status_code == 429:
                raise ProviderError("provider_rate_limited", "内容生成服务繁忙，请稍后重试")
            if response.status_code >= 400:
                raise ProviderError("provider_error", "内容生成失败，服务响应异常")
            data = _read_coze_stream(
                response,
                job_id=job["id"],
                workflow_code=job["workflow_code"],
            )
        except ProviderError as exc:
            if (
                job["workflow_code"] == "OWN01"
                and draft_attempt < draft_attempts
                and _is_retryable_book_provider_error(exc)
            ):
                logger.warning(
                    "coze_book_provider_retry job_id=%s attempt=%s/%s error=%s",
                    job["id"],
                    draft_attempt,
                    draft_attempts,
                    str(exc),
                )
                append_job_log(
                    job["id"],
                    "高分镜生成服务返回异常，正在自动降低分镜数重试",
                    level="warning",
                )
                continue
            raise
        finally:
            response.close()

        if job["workflow_code"] in LOCAL_CODES:
            try:
                return _save_draft_key_result(job, data)
            except ProviderError as exc:
                if (
                    exc.code == "incomplete_draft_key"
                    and draft_attempt < draft_attempts
                ):
                    logger.warning(
                        "coze_incomplete_draft_retry job_id=%s workflow=%s attempt=%s/%s",
                        job["id"],
                        job["workflow_code"],
                        draft_attempt,
                        draft_attempts,
                    )
                    append_job_log(
                        job["id"],
                        "首次生成的视频草稿缺少必要内容，正在自动重新生成"
                        f"（下一次为 {draft_attempt + 1}/{draft_attempts}）",
                        level="warning",
                    )
                    continue
                raise

        workflow = get_workflow(job["workflow_code"], job["category"]) or {}
        results = _extract_results(data, workflow.get("output_type", "draft"))
        if not results:
            raise ProviderError("empty_result", "工作流执行完成但没有可展示结果")
        return results

    raise ProviderError("incomplete_draft_key", "内容生成服务重复返回不完整的视频草稿")


def _decode_nested_json(value: Any) -> Any:
    """Decode JSON strings recursively without changing ordinary caption text."""
    if isinstance(value, dict):
        return {key: _decode_nested_json(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_decode_nested_json(child) for child in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return _decode_nested_json(json.loads(stripped))
            except (TypeError, ValueError):
                pass
    return value


def _find_nested_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        if field in value:
            return value[field]
        for child in value.values():
            found = _find_nested_field(child, field)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_nested_field(child, field)
            if found is not None:
                return found
    return None


_EXPECTED_PUBLISHED_DRAFT_CALL_IDS = {
    "OWN01": {
        "call_161537",
        "call_148232",
        "call_120409",
        "call_121846",
        "call_127166",
        "call_198946",
        "call_144998",
        "call_169833",
        "call_129095",
        "call_116900",
        "call_191365",
        "call_300101",
        "call_124102",
        "call_1713008",
        "call_143757",
        "call_138594",
    },
    "OWN02": {
        "call_990004",
        "call_113974",
        "call_151678",
        "call_150084",
        "call_166620",
        "call_483916",
        "call_100598",
        "call_293522",
        "call_848424",
        "call_195389",
        "call_194484",
        "call_557577",
        "call_175877",
        "call_273408",
        "call_1733515",
        "call_190819",
        "call_108008",
        "call_916607",
        "call_698411",
    },
}

# Workflow-specific nodes that may legitimately be absent from a published
# draft.  The book workflow deliberately has no optional image nodes: missing
# body artwork would expose the source template's previous book throughout.
_OPTIONAL_PUBLISHED_DRAFT_CALL_IDS = {
    # Book body images and their motion keyframes are required.  If they are
    # missing, JianYing keeps the source template's old book artwork visible.
    "OWN01": set(),
    "OWN02": {
        "call_501522",
        "call_731224",
        "call_639486",
        "call_828956",
        "call_884316",
        "call_872905",
        "call_555014",
        "call_692446",
        "call_835065",
        "call_874020",
    },
}


def _validate_published_draft_completeness(job: dict, draft_key: dict) -> None:
    code = str(job.get("workflow_code") or "").upper()
    calls = draft_key.get("calls")
    if not isinstance(calls, list):
        calls = []
    damaged_caption_ids = []
    empty_required_image_ids = []
    for call in calls:
        if not isinstance(call, dict) or call.get("tool") != "add_captions":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        captions = params.get("captions")
        if not isinstance(captions, list):
            continue
        if any(
            isinstance(caption, dict)
            and _visible_text_has_encoding_damage(str(caption.get("text") or ""))
            for caption in captions
        ):
            damaged_caption_ids.append(str(call.get("call_id") or "unknown"))

    required_image_call_ids = {
        # A book draft without body images silently exposes the source
        # template's previous title and artwork throughout the narration.
        "OWN01": {"call_191365"},
        # Fixed intro/background artwork is not a substitute for the
        # generated mythology subject images used by the body.
        "OWN03": {"main_images"},
    }.get(code, set())
    for call_id in sorted(required_image_call_ids):
        image_call = next(
            (
                item
                for item in calls
                if isinstance(item, dict)
                and str(item.get("call_id") or "") == call_id
                and item.get("tool") == "add_images"
            ),
            None,
        )
        params = (
            image_call.get("params")
            if isinstance((image_call or {}).get("params"), dict)
            else {}
        )
        image_infos = params.get("image_infos")
        if not isinstance(image_infos, list) or not any(
            isinstance(info, dict) and str(info.get("image_url") or "").strip()
            for info in image_infos
        ):
            empty_required_image_ids.append(call_id)

    expected_ids = _EXPECTED_PUBLISHED_DRAFT_CALL_IDS.get(code, set())
    if not expected_ids and not damaged_caption_ids and not empty_required_image_ids:
        return

    actual_ids = {
        str(call.get("call_id") or "")
        for call in calls
        if isinstance(call, dict)
    } if isinstance(calls, list) else set()
    optional_ids = _OPTIONAL_PUBLISHED_DRAFT_CALL_IDS.get(code, set())
    missing_ids = sorted(expected_ids - optional_ids - actual_ids)
    meta = draft_key.get("meta") if isinstance(draft_key.get("meta"), dict) else {}
    unresolved = [
        str(value)
        for value in (meta.get("unresolved_segment_ids") or [])
        if str(value)
    ]
    if not missing_ids and not unresolved and not damaged_caption_ids and not empty_required_image_ids:
        return

    skipped_titles = {
        str(item.get("call_id") or ""): str(item.get("source_node_title") or "")
        for item in (meta.get("skipped_empty_calls") or [])
        if isinstance(item, dict)
    }
    details = []
    if missing_ids:
        labelled = [
            f"{call_id}（内容生成节点「{skipped_titles[call_id]}」输出为空）"
            if skipped_titles.get(call_id)
            else call_id
            for call_id in missing_ids
        ]
        details.append("缺少操作节点：" + "、".join(labelled))
    if unresolved:
        details.append("存在未解析片段：" + "、".join(sorted(set(unresolved))[:10]))
    if damaged_caption_ids:
        details.append("存在乱码字幕：" + "、".join(sorted(set(damaged_caption_ids))))
    if empty_required_image_ids:
        details.append("必须主体图片为空：" + "、".join(empty_required_image_ids))

    job_id = str(job.get("id") or "").strip()
    if job_id:
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        rejected_file = RESULT_DIR / f"{code.lower()}-{job_id}-draft-key-rejected.json"
        try:
            rejected_file.write_text(json.dumps(draft_key, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.warning(
                "draft_key_rejected job_id=%s workflow=%s file=%s missing=%s unresolved=%s damaged_captions=%s empty_required_images=%s",
                job_id,
                code,
                rejected_file.name,
                ",".join(missing_ids) or "-",
                len(unresolved),
                ",".join(sorted(set(damaged_caption_ids))) or "-",
                ",".join(empty_required_image_ids) or "-",
            )
        except OSError:
            logger.exception("draft_key_reject_dump_failed job_id=%s", job_id)
    public_details = []
    skipped_text = " ".join(skipped_titles.get(call_id, "") for call_id in missing_ids)
    if missing_ids:
        if any(keyword in skipped_text for keyword in ("配图", "关键帧", "图片", "画面")):
            public_details.append("部分正文配图或关键帧没有生成完整")
        else:
            public_details.append("部分画面素材没有生成完整")
    if unresolved:
        public_details.append("部分分镜片段没有匹配到素材")
    if damaged_caption_ids:
        public_details.append("部分字幕发生编码损坏")
    if empty_required_image_ids:
        public_details.append("主体配图没有生成成功")
    public_suffix = "；".join(public_details) or "部分素材没有生成完整"
    raise ProviderError(
        "incomplete_draft_key",
        f"生成的视频草稿不完整，已阻止导入剪映；{public_suffix}。请重新生成一次，或换一个主题/素材后再试",
    )


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _repair_own01_missing_body_images(job: dict, draft_key: dict) -> None:
    """Deprecated: do not synthesize body images from intro visuals."""
    return
    if str(job.get("workflow_code") or "").upper() != "OWN01":
        return
    calls = draft_key.get("calls")
    if not isinstance(calls, list):
        return
    existing_ids = {str(call.get("call_id") or "") for call in calls if isinstance(call, dict)}
    repair_ids = {"call_191365", "call_300101"}
    if not repair_ids.issubset(_EXPECTED_PUBLISHED_DRAFT_CALL_IDS["OWN01"] - existing_ids):
        return

    body_caption_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict) and str(call.get("call_id") or "") == "call_143757"
        ),
        None,
    )
    body_captions = _as_list(((body_caption_call or {}).get("params") or {}).get("captions"))
    timelines = []
    for caption in body_captions:
        if not isinstance(caption, dict):
            continue
        start = int(float(caption.get("start") or 0))
        end = int(float(caption.get("end") or 0))
        if end > start:
            timelines.append({"start": start, "end": end})
    if not timelines:
        return

    source_images = []
    priority = {"call_169833": 0, "call_198946": 1, "call_144998": 2}
    image_calls = sorted(
        [
            call
            for call in calls
            if isinstance(call, dict) and call.get("tool") == "add_images"
        ],
        key=lambda call: priority.get(str(call.get("call_id") or ""), 99),
    )
    seen_urls = set()
    for call in image_calls:
        for info in _as_list((call.get("params") or {}).get("image_infos")):
            if not isinstance(info, dict):
                continue
            image_url = str(info.get("image_url") or "").strip()
            if not image_url or image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            source_images.append(
                {
                    "image_url": image_url,
                    "width": int(float(info.get("width") or 1024)),
                    "height": int(float(info.get("height") or 1024)),
                }
            )
    if not source_images:
        return

    body_images = []
    for index, timeline in enumerate(timelines):
        source = source_images[index % len(source_images)]
        body_images.append(
            {
                **source,
                "start": timeline["start"],
                "end": timeline["end"],
                "in_animation_duration": 120000,
                "out_animation_duration": 120000,
            }
        )

    keyframes = []
    for index, image_info in enumerate(body_images):
        duration = max(1, int(image_info["end"]) - int(image_info["start"]))
        ref = {"call_id": "call_191365", "index": index}
        keyframes.extend(
            [
                {"segment_ref": ref, "property": "KFTypePositionX", "offset": 0, "value": 0.0},
                {"segment_ref": ref, "property": "KFTypePositionX", "offset": duration, "value": 0.03 if index % 2 == 0 else -0.03},
                {"segment_ref": ref, "property": "KFTypePositionY", "offset": 0, "value": 0.0},
                {"segment_ref": ref, "property": "KFTypePositionY", "offset": duration, "value": -0.04 if index % 2 == 0 else 0.04},
                {"segment_ref": ref, "property": "UNIFORM_SCALE", "offset": 0, "value": 1.18},
                {"segment_ref": ref, "property": "UNIFORM_SCALE", "offset": duration, "value": 1.28},
            ]
        )

    calls.append(
        {
            "call_id": "call_191365",
            "tool": "add_images",
            "params": {
                "image_infos": body_images,
                "scale_x": 1.12,
                "scale_y": 1.12,
            },
        }
    )
    calls.append(
        {
            "call_id": "call_300101",
            "tool": "add_keyframes",
            "params": {"keyframes": keyframes},
        }
    )

    meta = draft_key.setdefault("meta", {})
    if isinstance(meta, dict):
        skipped = [
            item
            for item in _as_list(meta.get("skipped_empty_calls"))
            if str((item or {}).get("call_id") or "") not in repair_ids
        ]
        meta["skipped_empty_calls"] = skipped
        meta["fallback_repaired_calls"] = sorted(repair_ids)
    logger.warning(
        "own01_body_images_repaired job_id=%s images=%s keyframes=%s",
        job.get("id") or "-",
        len(body_images),
        len(keyframes),
    )
    if job.get("id"):
        append_job_log(
            str(job["id"]),
            "正文配图生成不完整，已自动使用封面图补齐画面",
            level="warning",
        )


def _draft_time_to_us(value: Any) -> int:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if abs(number) < 10_000:
        return max(0, int(round(number * 1_000_000)))
    return max(0, int(round(number)))


_OWN01_CAPTION_LINE_CHARS = 9
_OWN01_CAPTION_SOFT_LINE_CHARS = 11
_OWN01_CAPTION_MAX_CHARS = _OWN01_CAPTION_LINE_CHARS * 2
_OWN01_CAPTION_BREAKS = "，。！？；、：,.!?;:"
_OWN01_CAPTION_PERIODS = "。."
_OWN01_CAPTION_TRAILING_COMMAS = "，,"
_OWN01_CAPTION_CONNECTORS = "的地得"
_OWN01_CAPTION_NO_LINE_END = "的地得与和及或而这那该此每各也又都仍还更再正将把被从向对给为因于"
_OWN01_CAPTION_NO_LINE_START = "的地得中里上下内外着了过而与和及或"
_OWN01_CAPTION_PREDICATE_ENDINGS = (
    "见过",
    "看见",
    "看到",
    "发现",
    "听见",
    "懂得",
    "明白",
    "记得",
    "知道",
)
_OWN01_CAPTION_MIN_CHUNK_CHARS = 4
_OWN01_CAPTION_UNSAFE_WRAP_SCORE = 200
_OWN01_CAPTION_TRANSFORM_Y = -1200


def _own01_caption_chars(value: Any) -> list[str]:
    """Return visible caption characters without provider-added line breaks."""
    text = str(value or "").replace("\r", "").replace("\n", "").strip()
    return list(text)


def _own01_is_han_character(value: str) -> bool:
    return bool(value) and "\u3400" <= value <= "\u9fff"


def _own01_connector_spans(chars: list[str]) -> list[tuple[int, int]]:
    """Return short Chinese phrases joined by 的/地/得 as protected spans."""
    spans: list[tuple[int, int]] = []
    for index, char in enumerate(chars):
        if char not in _OWN01_CAPTION_CONNECTORS:
            continue

        start = index
        left_count = 0
        while (
            start > 0
            and left_count < 3
            and _own01_is_han_character(chars[start - 1])
        ):
            start -= 1
            left_count += 1

        end = index + 1
        right_count = 0
        while (
            end < len(chars)
            and right_count < 4
            and _own01_is_han_character(chars[end])
        ):
            end += 1
            right_count += 1
        spans.append((start, end))
    return spans


@lru_cache(maxsize=1024)
def _own01_caption_word_breaks(text: str) -> frozenset[int]:
    """Return safe Chinese word boundaries, with a dependency-free fallback."""
    try:
        import jieba

        jieba.setLogLevel(logging.WARNING)
        # Dictionary mode is deterministic and avoids HMM guesses such as
        # treating "中跌" as one word, which can then split "跌撞" in half.
        words = jieba.lcut(text, HMM=False)
    except (ImportError, UnicodeError, ValueError):
        return frozenset(range(1, len(text)))

    if "".join(words) != text:
        return frozenset(range(1, len(text)))
    boundaries: set[int] = set()
    offset = 0
    for word in words[:-1]:
        offset += len(word)
        boundaries.add(offset)
    return frozenset(boundaries)


def _own01_caption_break_penalty(chars: list[str], break_at: int) -> int:
    """Penalize breaks that tear apart short modifier phrases."""
    if break_at <= 0 or break_at >= len(chars):
        return 0

    penalty = 0
    if chars[break_at - 1] in _OWN01_CAPTION_CONNECTORS:
        penalty += 200
    if chars[break_at] in _OWN01_CAPTION_CONNECTORS:
        penalty += 200
    if any(start < break_at < end for start, end in _own01_connector_spans(chars)):
        penalty += 80
    if chars[break_at - 1] in _OWN01_CAPTION_NO_LINE_END:
        penalty += 160
    word_breaks = _own01_caption_word_breaks("".join(chars))
    next_word_end = min(
        (boundary for boundary in word_breaks if boundary > break_at),
        default=len(chars),
    )
    starts_multi_character_word = next_word_end > break_at + 1
    if (
        chars[break_at] in _OWN01_CAPTION_NO_LINE_START
        and not (
            chars[break_at] in "而与和及或"
            and starts_multi_character_word
        )
    ):
        penalty += 160
    if chars[break_at] in _OWN01_CAPTION_BREAKS:
        penalty += 500
    if break_at not in word_breaks:
        penalty += 300
    return penalty


def _own01_caption_predicate_break_bonus(chars: list[str], break_at: int) -> int:
    left = "".join(chars[:break_at]).rstrip(_OWN01_CAPTION_BREAKS)
    if any(left.endswith(ending) for ending in _OWN01_CAPTION_PREDICATE_ENDINGS):
        return 120
    return 0


def _own01_caption_line_break_score(chars: list[str], break_at: int) -> float:
    midpoint = len(chars) / 2
    overflow = max(0, break_at - _OWN01_CAPTION_LINE_CHARS) + max(
        0,
        len(chars) - break_at - _OWN01_CAPTION_LINE_CHARS,
    )
    return (
        _own01_caption_break_penalty(chars, break_at)
        + (
            80
            if min(break_at, len(chars) - break_at) < _OWN01_CAPTION_MIN_CHUNK_CHARS
            else 0
        )
        - (100 if chars[break_at - 1] in _OWN01_CAPTION_BREAKS else 0)
        - _own01_caption_predicate_break_bonus(chars, break_at)
        + (overflow * 20)
        + abs(break_at - midpoint)
    )


def _own01_caption_line_break_candidates(chars: list[str]) -> list[int]:
    lower = max(1, len(chars) - _OWN01_CAPTION_LINE_CHARS)
    upper = min(_OWN01_CAPTION_LINE_CHARS, len(chars) - 1)
    candidates = set(range(lower, upper + 1))

    soft_lower = max(1, len(chars) - _OWN01_CAPTION_SOFT_LINE_CHARS)
    soft_upper = min(_OWN01_CAPTION_SOFT_LINE_CHARS, len(chars) - 1)
    candidates.update(
        index
        for index in range(soft_lower, soft_upper + 1)
        if _own01_caption_predicate_break_bonus(chars, index)
    )
    return sorted(candidates)


def _own01_caption_wrap_penalty(chars: list[str]) -> float:
    if len(chars) <= _OWN01_CAPTION_LINE_CHARS:
        return 0
    return min(
        _own01_caption_line_break_score(chars, index)
        for index in _own01_caption_line_break_candidates(chars)
    )


def _own01_split_caption_text(value: Any) -> list[str]:
    """Split book narration into captions that render on at most two lines."""
    chars = _own01_caption_chars(value)
    if not chars:
        return []

    chunks: list[list[str]] = []
    offset = 0
    while offset < len(chars):
        end = min(len(chars), offset + _OWN01_CAPTION_MAX_CHARS)
        if 0 < len(chars) - end < _OWN01_CAPTION_MIN_CHUNK_CHARS:
            end = len(chars) - _OWN01_CAPTION_MIN_CHUNK_CHARS
        if end - offset > _OWN01_CAPTION_LINE_CHARS:
            # Score every feasible page boundary. Punctuation is the strongest
            # pause, followed by a complete word boundary; the hard visual
            # limit is used only when no semantic boundary is available. Even
            # text shorter than 18 characters becomes two pages when it cannot
            # form two clean nine-character lines on a single page.
            upper = end
            lower = offset + _OWN01_CAPTION_MIN_CHUNK_CHARS
            candidates = [
                candidate
                for candidate in range(lower, max(lower, upper) + 1)
                if candidate == len(chars)
                or len(chars) - candidate >= _OWN01_CAPTION_MIN_CHUNK_CHARS
            ]
            end = min(
                candidates,
                key=lambda candidate: (
                    _own01_caption_break_penalty(chars, candidate)
                    - (
                        180
                        if candidate < len(chars)
                        and chars[candidate - 1] in _OWN01_CAPTION_BREAKS
                        else 0
                    )
                    + (upper - candidate)
                    + _own01_caption_wrap_penalty(chars[offset:candidate]),
                    _own01_caption_wrap_penalty(chars[offset:candidate]),
                    abs(candidate - upper),
                ),
            )
        chunks.append(chars[offset:end])
        offset = end

    wrapped: list[str] = []
    for chunk in chunks:
        if len(chunk) <= _OWN01_CAPTION_LINE_CHARS:
            wrapped.append("".join(chunk))
            continue
        if (
            len(chunk) <= _OWN01_CAPTION_SOFT_LINE_CHARS
            and _own01_caption_wrap_penalty(chunk) >= _OWN01_CAPTION_UNSAFE_WRAP_SCORE
        ):
            # A slightly longer intact phrase is preferable to a short but
            # grammatically broken line such as "在战争 / 与和平的交织中".
            wrapped.append("".join(chunk))
            continue

        midpoint = len(chunk) / 2
        candidates = _own01_caption_line_break_candidates(chunk)
        split_at = min(
            candidates,
            key=lambda index: (
                _own01_caption_line_break_score(chunk, index),
                abs(index - midpoint),
            ),
        )
        wrapped.append("".join(chunk[:split_at]) + "\n" + "".join(chunk[split_at:]))
    return [
        cleaned
        for item in wrapped
        if (
            cleaned := item.translate(
                str.maketrans("", "", _OWN01_CAPTION_PERIODS)
            ).strip().rstrip(_OWN01_CAPTION_TRAILING_COMMAS).rstrip()
        )
    ]


def _own01_split_caption(caption: dict[str, Any]) -> list[dict[str, Any]]:
    parts = _own01_split_caption_text(caption.get("text"))
    if len(parts) <= 1:
        if parts:
            caption["text"] = parts[0]
        return [caption]

    start = _draft_time_to_us(caption.get("start"))
    end = _draft_time_to_us(caption.get("end"))
    duration = max(0, end - start)
    weights = [max(1, len(part.replace("\n", ""))) for part in parts]
    total_weight = sum(weights)
    result: list[dict[str, Any]] = []
    elapsed_weight = 0
    for index, (part, weight) in enumerate(zip(parts, weights)):
        item = dict(caption)
        item["text"] = part
        item["start"] = start + round(duration * elapsed_weight / total_weight)
        elapsed_weight += weight
        item["end"] = end if index == len(parts) - 1 else start + round(duration * elapsed_weight / total_weight)
        result.append(item)
    return result


# The provider occasionally returns aliases from a newer Jianying catalog.
# Older desktop assistants do not have those resource ids and silently drop
# the animation (or fail the quality check).  Keep the intended motion by
# translating only the known aliases to the equivalent, widely available
# intro resources.  Other names are left untouched so newly installed
# Jianying versions can use them directly.
_IMAGE_INTRO_ANIMATION_ALIASES = {
    # Kira游动 is present in the helper catalog on both Jianying 5.9 and
    # 11.x.  The plain zoom resources are not consistently present there,
    # so use this animated fallback instead of dropping motion entirely.
    "动感缩小": "Kira游动",
    "轻微放大": "Kira游动",
    "缩小": "Kira游动",
    "放大": "Kira游动",
}


def _normalize_image_intro_animation(value: Any) -> str:
    name = str(value or "").strip()
    return _IMAGE_INTRO_ANIMATION_ALIASES.get(name, name)


def _attach_animation_resource_ids(info: dict[str, Any], name_key: str, type_key: str, prefix: str) -> None:
    """Embed catalog ids so the Windows helper can keep named animations.

    Helper versions may ship an older display-name catalog.  The resource id
    is the stable Jianying reference, so include it in the draft key whenever
    our server catalog knows the requested animation.
    """
    name = str(info.get(name_key) or "").strip()
    if not name:
        return
    table = {
        ("video", "in"): "video_intros",
        ("video", "out"): "video_outros",
        ("video", "group"): "video_group_animations",
        ("text", "in"): "text_intros",
        ("text", "out"): "text_outros",
        ("text", "loop"): "text_loops",
    }.get((prefix, type_key))
    if not table:
        return
    try:
        from utils.jianying_drafts import _lookup_meta

        meta = _lookup_meta(table, name) or {}
    except Exception:
        meta = {}
    if meta.get("resource_id"):
        info.setdefault(f"{name_key}_resource_id", str(meta["resource_id"]))
    if meta.get("effect_id"):
        info.setdefault(f"{name_key}_effect_id", str(meta["effect_id"]))


def _strengthen_own01_image_motion(draft_key: dict) -> None:
    """Give every book image an obvious, JianYing-safe camera move.

    Two-point camera moves are the most reliable shape in JianYing 11.  Keep
    the last point away from the exact segment boundary and normalize weak
    provider motion as well as the final image.  This avoids both barely
    visible early shots and a completely static final shot.
    """

    calls = draft_key.get("calls") if isinstance(draft_key.get("calls"), list) else []
    image_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict)
            and str(call.get("call_id") or "") == "call_191365"
            and isinstance((call.get("params") or {}).get("image_infos"), list)
        ),
        None,
    )
    image_infos = ((image_call or {}).get("params") or {}).get("image_infos") or []
    valid_indexes = [index for index, info in enumerate(image_infos) if isinstance(info, dict)]
    if not valid_indexes:
        return
    keyframe_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict)
            and str(call.get("call_id") or "") == "call_300101"
            and isinstance((call.get("params") or {}).get("keyframes"), list)
        ),
        None,
    )
    if keyframe_call is None:
        keyframe_call = {
            "call_id": "call_300101",
            "tool": "add_keyframes",
            "params": {"keyframes": []},
        }
        calls.append(keyframe_call)

    keyframes = keyframe_call["params"]["keyframes"]
    target_properties = {
        "KFTypePositionX",
        "KFTypePositionY",
        "UNIFORM_SCALE",
        "KFTypeUniformScale",
    }
    retained: list[dict[str, Any]] = []
    existing_by_index: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for keyframe in keyframes:
        if not isinstance(keyframe, dict):
            continue
        ref = keyframe.get("segment_ref")
        try:
            ref_index = int(ref.get("index", -1)) if isinstance(ref, dict) else -1
        except (TypeError, ValueError):
            ref_index = -1
        is_body_image = (
            isinstance(ref, dict)
            and str(ref.get("call_id") or "") == "call_191365"
            and ref_index in valid_indexes
        )
        prop = str(keyframe.get("property") or keyframe.get("property_type") or "")
        if is_body_image and prop in target_properties:
            normalized_prop = "UNIFORM_SCALE" if prop == "KFTypeUniformScale" else prop
            existing_by_index.setdefault(ref_index, {}).setdefault(normalized_prop, []).append(keyframe)
            continue
        retained.append(keyframe)

    repaired_indexes: list[int] = []
    for index in valid_indexes:
        info = image_infos[index]
        duration = _draft_time_to_us(info.get("end")) - _draft_time_to_us(info.get("start"))
        if duration < 1_000_000:
            continue

        direction = -1.0 if index % 2 else 1.0
        ref = {"call_id": "call_191365", "index": index}
        for prop, points in _continuous_motion_points(
            duration,
            direction=direction,
            strong=True,
        ).items():
            for offset, value in points:
                retained.append(
                    {
                        "segment_ref": ref,
                        "property": prop,
                        "offset": offset,
                        "value": round(float(value), 4),
                    }
                )
        repaired_indexes.append(index)
    keyframe_call["params"]["keyframes"] = retained

    meta = draft_key.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["final_image_motion_repaired"] = True
        meta["book_image_motion_repaired_indexes"] = repaired_indexes


def _strengthen_own01_tail_motion(draft_key: dict) -> None:
    """Keep the separately layered final book image visibly moving too."""

    calls = draft_key.get("calls") if isinstance(draft_key.get("calls"), list) else []
    image_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict)
            and call.get("call_id") == "call_191365_tail"
            and isinstance((call.get("params") or {}).get("image_infos"), list)
        ),
        None,
    )
    keyframe_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict)
            and call.get("call_id") == "call_300101_tail"
            and isinstance((call.get("params") or {}).get("keyframes"), list)
        ),
        None,
    )
    images = ((image_call or {}).get("params") or {}).get("image_infos") or []
    if not images or keyframe_call is None:
        return
    info = images[0]
    duration = _draft_time_to_us(info.get("end")) - _draft_time_to_us(info.get("start"))
    if duration < 1_000_000:
        return

    target_properties = {
        "KFTypePositionX",
        "KFTypePositionY",
        "UNIFORM_SCALE",
        "KFTypeUniformScale",
    }
    retained = []
    for keyframe in keyframe_call["params"]["keyframes"]:
        if not isinstance(keyframe, dict):
            continue
        ref = keyframe.get("segment_ref")
        prop = str(keyframe.get("property") or keyframe.get("property_type") or "")
        try:
            ref_index = int(ref.get("index", -1)) if isinstance(ref, dict) else -1
        except (TypeError, ValueError):
            ref_index = -1
        if (
            isinstance(ref, dict)
            and ref.get("call_id") == "call_191365_tail"
            and ref_index == 0
            and prop in target_properties
        ):
            continue
        retained.append(keyframe)

    ref = {"call_id": "call_191365_tail", "index": 0}
    for prop, points in _continuous_motion_points(
        duration,
        direction=-1.0,
        strong=True,
    ).items():
        for offset, value in points:
            retained.append(
                {
                    "segment_ref": ref,
                    "property": prop,
                    "offset": offset,
                    "value": round(float(value), 4),
                }
            )
    keyframe_call["params"]["keyframes"] = retained
    meta = draft_key.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["book_tail_motion_repaired"] = True


def _bridge_own01_opening_body_gap(draft_key: dict) -> None:
    """Hold the final opening frame until the first body image begins."""

    calls = draft_key.get("calls") if isinstance(draft_key.get("calls"), list) else []
    body_call_ids = {"call_191365", "call_191365_tail"}
    body_starts: list[int] = []
    for call in calls:
        if not isinstance(call, dict) or str(call.get("call_id") or "") not in body_call_ids:
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        for info in params.get("image_infos") or []:
            if isinstance(info, dict):
                start = _draft_time_to_us(info.get("start"))
                if start > 0:
                    body_starts.append(start)
    if not body_starts:
        return
    first_body_start = min(body_starts)

    latest_info: dict[str, Any] | None = None
    latest_end = 0
    latest_call_id = ""
    for call in calls:
        if not isinstance(call, dict) or call.get("tool") != "add_images":
            continue
        call_id = str(call.get("call_id") or "")
        if call_id in body_call_ids:
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        for info in params.get("image_infos") or []:
            if not isinstance(info, dict):
                continue
            end = _draft_time_to_us(info.get("end"))
            if latest_end < end <= first_body_start:
                latest_info = info
                latest_end = end
                latest_call_id = call_id

    gap = first_body_start - latest_end
    if latest_info is None or gap <= 10_000 or gap > 2_000_000:
        return
    latest_info["end"] = first_body_start
    meta = draft_key.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["book_opening_gap_repaired"] = {
            "call_id": latest_call_id,
            "old_end": latest_end,
            "new_end": first_body_start,
            "gap_us": gap,
        }


def _continuous_motion_points(
    duration: int,
    *,
    direction: float,
    strong: bool = False,
) -> dict[str, list[tuple[int, float]]]:
    """Return an in-range three-point camera move for one image segment."""

    safe_end = max(1, duration - min(300_000, max(1, duration // 20)))
    midpoint = max(1, min(safe_end - 1, safe_end // 2))
    pan_x = 0.10 if strong else 0.065
    pan_y = 0.07 if strong else 0.045
    low_scale = 1.18 if strong else 1.12
    high_scale = 1.50 if strong else 1.26
    settle_scale = 1.28 if strong else 1.16
    return {
        "KFTypePositionX": [
            (0, -pan_x * direction),
            (midpoint, pan_x * direction),
            (safe_end, -pan_x * 0.4 * direction),
        ],
        "KFTypePositionY": [
            (0, pan_y * direction),
            (midpoint, -pan_y * direction),
            (safe_end, pan_y * 0.4 * direction),
        ],
        "UNIFORM_SCALE": [
            (0, low_scale),
            (midpoint, high_scale),
            (safe_end, settle_scale),
        ],
    }


def _strengthen_own03_image_motion(draft_key: dict) -> None:
    """Give every mythology scene, including its tail split, full-duration motion.

    Some provider drafts contain camera offsets longer than the referenced
    segment and omit the split tail entirely. JianYing may then stop applying
    camera keyframes from that point onward. Replace only image camera motion
    with bounded points while preserving the template's named animations.
    """

    calls = draft_key.get("calls") if isinstance(draft_key.get("calls"), list) else []
    target_calls: list[tuple[str, list[dict[str, Any]]]] = []
    for call_id in ("main_images", "main_tail_images"):
        image_call = next(
            (
                call
                for call in calls
                if isinstance(call, dict)
                and str(call.get("call_id") or "") == call_id
                and isinstance((call.get("params") or {}).get("image_infos"), list)
            ),
            None,
        )
        if image_call is not None:
            target_calls.append((call_id, image_call["params"]["image_infos"]))
    if not target_calls:
        return

    target_ids = {call_id for call_id, _infos in target_calls}
    target_properties = {
        "KFTypePositionX",
        "KFTypePositionY",
        "UNIFORM_SCALE",
        "KFTypeUniformScale",
    }
    for call in calls:
        if not isinstance(call, dict) or call.get("tool") != "add_keyframes":
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        keyframes = params.get("keyframes") if isinstance(params.get("keyframes"), list) else []
        retained = []
        for keyframe in keyframes:
            if not isinstance(keyframe, dict):
                continue
            ref = keyframe.get("segment_ref")
            prop = str(keyframe.get("property") or keyframe.get("property_type") or "")
            if (
                isinstance(ref, dict)
                and str(ref.get("call_id") or "") in target_ids
                and prop in target_properties
            ):
                continue
            retained.append(keyframe)
        params["keyframes"] = retained

    continuous_frames: list[dict[str, Any]] = []
    repaired_refs: list[str] = []
    sequence_index = 0
    for call_id, image_infos in target_calls:
        for index, info in enumerate(image_infos):
            if not isinstance(info, dict):
                continue
            duration = _draft_time_to_us(info.get("end")) - _draft_time_to_us(info.get("start"))
            if duration < 500_000:
                continue
            direction = 1.0 if sequence_index % 2 == 0 else -1.0
            ref = {"call_id": call_id, "index": index}
            for prop, points in _continuous_motion_points(
                duration,
                direction=direction,
            ).items():
                for offset, value in points:
                    continuous_frames.append(
                        {
                            "segment_ref": ref,
                            "property": prop,
                            "offset": offset,
                            "value": round(float(value), 4),
                        }
                    )
            repaired_refs.append(f"{call_id}:{index}")
            sequence_index += 1

    if not continuous_frames:
        return
    calls[:] = [
        call
        for call in calls
        if not (
            isinstance(call, dict)
            and (
                call.get("call_id") == "camera_kf_continuous"
                or (
                    call.get("tool") == "add_keyframes"
                    and isinstance((call.get("params") or {}).get("keyframes"), list)
                    and not (call.get("params") or {}).get("keyframes")
                )
            )
        )
    ]
    calls.append(
        {
            "call_id": "camera_kf_continuous",
            "tool": "add_keyframes",
            "params": {"keyframes": continuous_frames},
        }
    )
    meta = draft_key.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["god_continuous_motion_repaired_refs"] = repaired_refs


def _separate_own01_final_image_track(draft_key: dict) -> None:
    """Put the final book image above the preceding body-image lane.

    Older helpers extend the latest early-ending photo to the narration tail
    as black-screen protection.  With sequential book photos that can make the
    penultimate photo overlap and hide the real final one in JianYing 11.  A
    dedicated higher render lane keeps the final image and its camera move
    visible even when that compatibility extension is applied.
    """

    calls = draft_key.get("calls") if isinstance(draft_key.get("calls"), list) else []
    existing_tail = next(
        (
            call
            for call in calls
            if isinstance(call, dict) and call.get("call_id") == "call_191365_tail"
        ),
        None,
    )
    if existing_tail is not None:
        existing_tail["track_name"] = "video_book_final"
        existing_tail["render_index"] = 14500
        return

    image_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict)
            and call.get("call_id") == "call_191365"
            and isinstance((call.get("params") or {}).get("image_infos"), list)
        ),
        None,
    )
    image_infos = ((image_call or {}).get("params") or {}).get("image_infos") or []
    if len(image_infos) < 2:
        return
    keyframe_call = next(
        (
            call
            for call in calls
            if isinstance(call, dict)
            and call.get("call_id") == "call_300101"
            and isinstance((call.get("params") or {}).get("keyframes"), list)
        ),
        None,
    )
    if keyframe_call is None:
        return

    final_index = len(image_infos) - 1
    final_image = dict(image_infos.pop())
    retained_keyframes: list[dict[str, Any]] = []
    tail_keyframes: list[dict[str, Any]] = []
    for keyframe in keyframe_call["params"]["keyframes"]:
        if not isinstance(keyframe, dict):
            continue
        copied = dict(keyframe)
        ref = copied.get("segment_ref")
        try:
            ref_index = int(ref.get("index", -1)) if isinstance(ref, dict) else -1
        except (TypeError, ValueError):
            ref_index = -1
        if (
            isinstance(ref, dict)
            and ref.get("call_id") == "call_191365"
            and ref_index == final_index
        ):
            copied["segment_ref"] = {"call_id": "call_191365_tail", "index": 0}
            tail_keyframes.append(copied)
        else:
            retained_keyframes.append(copied)
    keyframe_call["params"]["keyframes"] = retained_keyframes

    tail_image_call = {
        "call_id": "call_191365_tail",
        "tool": "add_images",
        "source_node_id": "191365",
        "source_node_title": "添加正文末图",
        "track_name": "video_book_final",
        "render_index": 14500,
        "params": {"image_infos": [final_image], "scale_x": 1, "scale_y": 1},
    }
    tail_keyframe_call = {
        "call_id": "call_300101_tail",
        "tool": "add_keyframes",
        "source_node_id": "300101",
        "source_node_title": "添加正文末图关键帧",
        "params": {"keyframes": tail_keyframes},
    }
    calls.insert(calls.index(image_call) + 1, tail_image_call)
    calls.insert(calls.index(keyframe_call) + 1, tail_keyframe_call)

    meta = draft_key.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["book_final_image_separate_track"] = True
        meta["recorded_operation_count"] = len(calls)


def _normalize_published_draft_key(job: dict, draft_key: dict) -> None:
    workflow_code = str(job.get("workflow_code") or "").upper()
    if workflow_code == DRAFT_KEY_RENDER_CODE:
        meta = draft_key.get("meta") if isinstance(draft_key.get("meta"), dict) else {}
        marker = " ".join(str(meta.get(key) or "") for key in ("workflow", "title", "run_id")).lower()
        if "own03" in marker or "god" in marker or "神" in marker:
            workflow_code = "OWN03"
    if workflow_code == "OWN02":
        replacements = {
            "call_273408": _configured_visible_text(
                "CIGARETTE_LEFT_TOP_TEXT",
                "吸烟有害身体健康",
            ),
            "call_1733515": _configured_visible_text(
                "CIGARETTE_LEFT_TEXT",
                "未成年人禁止吸烟",
            ),
        }
        for call in draft_key.get("calls") or []:
            if not isinstance(call, dict):
                continue
            replacement = replacements.get(str(call.get("call_id") or ""))
            if replacement is None:
                continue
            params = call.get("params") if isinstance(call.get("params"), dict) else {}
            captions = params.get("captions")
            if not isinstance(captions, list):
                continue
            for caption in captions:
                if not isinstance(caption, dict):
                    continue
                text = str(caption.get("text") or "").strip()
                if not text or _visible_text_has_encoding_damage(text):
                    caption["text"] = replacement
        return
    if workflow_code == "OWN03":
        # Preserve the template's complete visual language.  In particular,
        # do not replace the named image animations, camera keyframes, or
        # opening sparkle lane; those are intentional parts of the template.
        calls = draft_key.get("calls") or []
        for call in calls:
            if not isinstance(call, dict):
                continue
            params = call.get("params") if isinstance(call.get("params"), dict) else {}
            if call.get("tool") == "add_images":
                for info in params.get("image_infos") or []:
                    if not isinstance(info, dict):
                        continue
                    for name_key, type_key in (("in_animation", "in"), ("out_animation", "out"), ("group_animation", "group")):
                        _attach_animation_resource_ids(info, name_key, type_key, "video")
                    # Some provider drafts stretch an entrance animation over
                    # the complete narration scene. JianYing 11.2.5 can stop
                    # rendering the photo when that animation resource reaches
                    # its native end, leaving only captions and the border.
                    # Keep the named template entrance short; the continuous
                    # camera keyframes below provide full-scene movement.
                    if str(call.get("call_id") or "") in {"main_images", "main_tail_images"}:
                        start = _draft_time_to_us(info.get("start"))
                        end = _draft_time_to_us(info.get("end"))
                        segment_duration = max(1, end - start)
                        entrance_duration = _draft_time_to_us(info.get("in_animation_duration"))
                        if info.get("in_animation") and entrance_duration > 0:
                            info["in_animation_duration"] = min(
                                entrance_duration,
                                segment_duration,
                                800_000,
                            )
            elif call.get("tool") == "add_captions":
                for info in params.get("captions") or []:
                    if not isinstance(info, dict):
                        continue
                    for name_key, type_key in (("in_animation", "in"), ("out_animation", "out"), ("loop_animation", "loop")):
                        _attach_animation_resource_ids(info, name_key, type_key, "text")
            elif call.get("tool") == "add_effects":
                effect_aliases = {
                    "柔光": ("6714239617916211716", "634095"),
                    "光晕": ("6714239617916211716", "634095"),
                    "梦幻": ("6894208129534267912", "961480"),
                    "金粉闪闪": ("7034048554318434830", "1453820"),
                }
                for info in params.get("effect_infos") or []:
                    if not isinstance(info, dict):
                        continue
                    name = str(info.get("effect_title") or info.get("effect") or info.get("name") or "").strip()
                    resource_id, effect_id = effect_aliases.get(name, ("", ""))
                    if resource_id:
                        info.setdefault("effect_resource_id", resource_id)
                        info.setdefault("effect_id", effect_id)
        # Preserve an explicitly split tail image lane. Older drafts may have
        # omitted its track name; upgrade it in place so it remains isolated.
        calls = draft_key.get("calls") or []
        existing_tail_calls = [
            call
            for call in calls
            if isinstance(call, dict)
            and str(call.get("call_id") or "") == "main_tail_images"
        ]
        main_call = next(
            (
                call
                for call in calls
                if isinstance(call, dict)
                and str(call.get("call_id") or "") == "main_images"
                and isinstance((call.get("params") or {}).get("image_infos"), list)
            ),
            None,
        )
        main_infos = ((main_call or {}).get("params") or {}).get("image_infos") or []
        valid_main_infos = [info for info in main_infos if isinstance(info, dict)]
        source_tail_info = valid_main_infos[-1] if valid_main_infos else None
        for tail_call in existing_tail_calls:
            tail_call.setdefault("track_name", "video_tail")
            tail_infos = ((tail_call.get("params") or {}).get("image_infos") or [])
            for tail_info in tail_infos:
                if not isinstance(tail_info, dict) or not source_tail_info:
                    continue
                # Drafts created before the tail fix already contain a tail
                # segment, but it was a freeze frame with no animation fields.
                # Repair that shape in place so re-renders of old jobs animate
                # as well instead of requiring a new source workflow export.
                for animation_key in (
                    "in_animation",
                    "in_animation_resource_id",
                    "in_animation_effect_id",
                    "out_animation",
                    "out_animation_resource_id",
                    "out_animation_effect_id",
                    "group_animation",
                    "group_animation_resource_id",
                    "group_animation_effect_id",
                ):
                    if not tail_info.get(animation_key) and source_tail_info.get(animation_key):
                        tail_info[animation_key] = source_tail_info[animation_key]
                tail_start = _draft_time_to_us(tail_info.get("start"))
                tail_end = _draft_time_to_us(tail_info.get("end"))
                tail_duration = max(1, tail_end - tail_start)
                for duration_key in (
                    "in_animation_duration",
                    "out_animation_duration",
                    "group_animation_duration",
                ):
                    if duration_key not in tail_info and duration_key in source_tail_info:
                        tail_info[duration_key] = source_tail_info[duration_key]
                    if duration_key in tail_info:
                        duration = _draft_time_to_us(tail_info.get(duration_key))
                        tail_info[duration_key] = min(duration, tail_duration) if duration > 0 else tail_duration
        if not existing_tail_calls:
            infos = ((main_call or {}).get("params") or {}).get("image_infos") or []
            valid_infos = [info for info in infos if isinstance(info, dict)]
            if valid_infos:
                last_info = valid_infos[-1]
                start = _draft_time_to_us(last_info.get("start"))
                end = _draft_time_to_us(last_info.get("end"))
                split = min(end - 1_500_000, start + 1_500_000)
                if start < split < end:
                    tail_info = dict(last_info)
                    last_info["end"] = split
                    tail_info["start"] = split
                    tail_info["end"] = end
                    # The tail is a safety split, not a static freeze frame.
                    # Keep the final image's animation metadata on the second
                    # adjacent segment and bound durations to the short tail.
                    tail_duration = max(1, end - split)
                    for duration_key in (
                        "in_animation_duration",
                        "out_animation_duration",
                        "group_animation_duration",
                    ):
                        if duration_key not in tail_info:
                            continue
                        duration = _draft_time_to_us(tail_info.get(duration_key))
                        tail_info[duration_key] = min(duration, tail_duration) if duration > 0 else tail_duration
                    tail_call = {
                        "call_id": "main_tail_images",
                        "tool": "add_images",
                        # The tail is sequential with the final main image,
                        # so JianYing keeps rendering it without an overlap.
                        "track_name": str(main_call.get("track_name") or "video_main"),
                        "params": {"image_infos": [tail_info]},
                    }
                    # Insert beside the main image lane.  Appending it after
                    # the background lane would put the full-frame tail above
                    # the border/template layer.
                    normalized_calls = list(calls)
                    normalized_calls.insert(normalized_calls.index(main_call) + 1, tail_call)
                    draft_key["calls"] = normalized_calls
        _strengthen_own03_image_motion(draft_key)
        return
    if workflow_code != "OWN01":
        return
    _bridge_own01_opening_body_gap(draft_key)
    _strengthen_own01_image_motion(draft_key)
    _separate_own01_final_image_track(draft_key)
    _strengthen_own01_tail_motion(draft_key)
    for call in draft_key.get("calls") or []:
        if not isinstance(call, dict):
            continue
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        captions = params.get("captions")
        if not isinstance(captions, list):
            continue
        if call.get("call_id") == "call_143757":
            params["transform_y"] = _OWN01_CAPTION_TRANSFORM_Y
            split_captions: list[dict[str, Any]] = []
            for caption in captions:
                if isinstance(caption, dict):
                    for split_caption in _own01_split_caption(caption):
                        split_caption["transform_y"] = _OWN01_CAPTION_TRANSFORM_Y
                        split_captions.append(split_caption)
            params["captions"] = split_captions
        elif call.get("call_id") == "call_138594":
            for caption in captions:
                if not isinstance(caption, dict):
                    continue
                # This is deliberately invisible text, not an empty value.
                caption["text"] = "  "


def _save_draft_key_result(job: dict, data: Any) -> list[dict]:
    draft_key = _decode_nested_json(_find_nested_field(data, "draft_key"))
    if draft_key is None and isinstance(data, dict) and isinstance(data.get("calls"), list):
        draft_key = data
    if not isinstance(draft_key, dict):
        raise ProviderError("draft_key_missing", "内容生成已完成，但返回结果中没有视频草稿")

    from utils.draft_key_importer import (
        KeyValidationError,
        deduplicate_exact_effect_calls,
        import_draft_key,
    )

    draft_key, removed_effect_calls = deduplicate_exact_effect_calls(draft_key)
    if removed_effect_calls:
        logger.warning(
            "duplicate_effect_calls_removed job_id=%s calls=%s",
            job.get("id") or "-",
            ",".join(removed_effect_calls),
        )
        if job.get("id"):
            append_job_log(
                str(job["id"]),
                "检测到完全重复的特效轨道，已自动去重：" + "、".join(removed_effect_calls),
                level="warning",
            )
    _normalize_published_draft_key(job, draft_key)
    _validate_published_draft_completeness(job, draft_key)

    try:
        import_draft_key(draft_key, dry_run=True)
    except KeyValidationError as exc:
        raise ProviderError("invalid_draft_key", "内容生成服务返回的视频草稿校验失败：" + "；".join(exc.errors)) from exc

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    destination = RESULT_DIR / f"{job['workflow_code'].lower()}-{job['id']}-draft-key.json"
    destination.write_text(json.dumps(draft_key, ensure_ascii=False, indent=2), encoding="utf-8")
    remote_draft_id = _find_nested_field(data, "draft_id")
    _update_job(job["id"], stage="draft_key_ready", progress=75)
    logger.info(
        "draft_key_saved job_id=%s workflow=%s file=%s",
        job["id"],
        job["workflow_code"],
        destination.name,
    )
    append_job_log(job["id"], "视频草稿已生成并通过校验")
    return [
        {
            "type": "draft",
            "format": "draft_key",
            "url": f"/api/v1/job-results/{destination.name}",
            "poster_url": None,
            "downloadable": True,
            "remote_draft_id": str(remote_draft_id or ""),
        }
    ]


def _save_local_draft_key_result(job: dict, draft_key: dict) -> list[dict]:
    """Persist a locally built draft_key without Coze node completeness checks."""
    from utils.draft_key_importer import KeyValidationError, import_draft_key

    try:
        import_draft_key(draft_key, dry_run=True)
    except KeyValidationError as exc:
        raise ProviderError("invalid_draft_key", "本地生成的视频草稿校验失败：" + "；".join(exc.errors)) from exc

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    destination = RESULT_DIR / f"{job['workflow_code'].lower()}-{job['id']}-draft-key.json"
    destination.write_text(json.dumps(draft_key, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_job(job["id"], stage="draft_key_ready", progress=75)
    append_job_log(job["id"], "视频草稿已生成并通过校验")
    return [
        {
            "type": "draft",
            "format": "draft_key",
            "url": f"/api/v1/job-results/{destination.name}",
            "poster_url": None,
            "downloadable": True,
            "remote_draft_id": "",
        }
    ]


def _build_local_draft_key(job: dict) -> dict[str, Any]:
    code = str(job.get("workflow_code") or "").upper()
    inputs = job.get("inputs") if isinstance(job.get("inputs"), dict) else {}
    theme = str(
        inputs.get("theme")
        or inputs.get("book_name")
        or inputs.get("cigarette_name")
        or inputs.get("god_name")
        or "未命名主题"
    ).strip() or "未命名主题"
    safe_theme = re.sub(r'[\\/:*?"<>|\r\n]+', "_", theme).strip(" .")[:40] or code
    duration = 8_000_000

    if code == "OWN01":
        title = theme
        subtitle = "一本书，一段被时间留下的回声。"
        body = "把最有记忆点的情绪、人物和金句整理成短视频草稿。"
        footer = "书单视频"
    elif code == "OWN02":
        title = theme
        subtitle = f"每天认识一种香烟之{theme}"
        body = "以包装、色彩和名字意象切入，生成克制的情绪独白。"
        footer = "香烟视频"
    elif code == "OWN03":
        title = theme
        subtitle = "神话人物，一分钟讲清核心气质。"
        body = "用开场悬念、人物标签和结尾反转搭建视频节奏。"
        footer = "神话解说"
    else:
        title = theme
        subtitle = "本地视频草稿"
        body = "内容已整理为可导出的剪映草稿。"
        footer = code

    return {
        "schema_version": "1.0",
        "kind": "jianying_draft_key",
        "meta": {
            "workflow": code,
            "run_id": str(job.get("id") or uuid.uuid4().hex),
            "title": title,
            "local_template_fallback": True,
        },
        "draft": {
            "width": 1080,
            "height": 1920,
            "name": f"{code}_{safe_theme}",
        },
        "calls": [
            {
                "call_id": "local_title",
                "tool": "add_captions",
                "params": {
                    "captions": [{"text": title, "start": 0, "end": duration}],
                    "font": "华文行楷",
                    "font_size": 16,
                    "text_color": "#F8E7B0",
                    "border_color": "#1D1208",
                    "transform_y": -520,
                    "in_animation": "渐显",
                    "in_animation_duration": 500_000,
                },
            },
            {
                "call_id": "local_subtitle",
                "tool": "add_captions",
                "params": {
                    "captions": [{"text": subtitle, "start": 600_000, "end": duration}],
                    "font": "华文行楷",
                    "font_size": 8,
                    "text_color": "#DFD5D5",
                    "border_color": "#000000",
                    "transform_y": -260,
                    "in_animation": "向上滑动",
                    "in_animation_duration": 400_000,
                },
            },
            {
                "call_id": "local_body",
                "tool": "add_captions",
                "params": {
                    "captions": [{"text": body, "start": 1_600_000, "end": duration}],
                    "font": "华文行楷",
                    "font_size": 7,
                    "text_color": "#FFFFFF",
                    "border_color": "#000000",
                    "transform_y": 120,
                    "line_spacing": 2,
                    "in_animation": "渐显",
                    "in_animation_duration": 500_000,
                },
            },
            {
                "call_id": "local_footer",
                "tool": "add_captions",
                "params": {
                    "captions": [{"text": footer, "start": 0, "end": duration}],
                    "font_size": 5,
                    "text_color": "#B8894B",
                    "transform_y": 760,
                },
            },
        ],
    }


def _extract_results(value: Any, expected_type: str = "draft") -> list[dict]:
    urls: list[tuple[str, str]] = []

    def visit(item, hint=""):
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, str(key).lower())
        elif isinstance(item, list):
            for child in item:
                visit(child, hint)
        elif isinstance(item, str):
            if item.startswith(("http://", "https://")):
                urls.append((item, hint))
            elif item.strip().startswith(("{", "[")):
                try:
                    visit(json.loads(item), hint)
                except ValueError:
                    pass

    visit(value)
    results = []
    seen = set()
    for url, hint in urls:
        if url in seen:
            continue
        seen.add(url)
        lower = url.lower().split("?")[0]
        if "draft" in hint or "jianying" in hint or "剪映" in hint:
            kind = "draft"
        elif lower.endswith((".mp4", ".mov", ".webm")):
            kind = "video"
        elif lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
            kind = "image"
        else:
            kind = expected_type if expected_type in {"image", "video"} else "draft"
        results.append({"type": kind, "url": url, "poster_url": None, "downloadable": True})
    return results


def _render_drafts(job: dict, results: list[dict]) -> list[dict]:
    """Send provider draft URLs to a server-side rendering service.

    The renderer contract is intentionally provider-neutral: it receives draft
    URLs and must return a JSON body containing at least one playable video URL.
    """
    render_url = (os.getenv("WORKFLOW_RENDER_API_URL") or "").strip()
    render_token = (os.getenv("WORKFLOW_RENDER_API_TOKEN") or "").strip()
    if not render_url:
        raise ProviderError("render_not_configured", "工作流返回了剪映草稿，但后台渲染服务尚未配置")

    _update_job(job["id"], status="rendering", stage="rendering", progress=75)
    logger.info(
        "render_request_started job_id=%s workflow=%s draft_count=%s",
        job["id"],
        job["workflow_code"],
        sum(result["type"] == "draft" for result in results),
    )
    append_job_log(job["id"], "视频草稿已提交云端渲染服务，正在生成视频")
    headers = {"Content-Type": "application/json"}
    if render_token:
        headers["Authorization"] = f"Bearer {render_token}"
    draft_key = _load_draft_key_result(results)
    request_body = {
        "job_id": job["id"],
        "workflow_code": job["workflow_code"],
        "drafts": [result["url"] for result in results if result["type"] == "draft"],
    }
    if draft_key is not None:
        request_body["draft_key"] = draft_key

    try:
        response = requests.post(
            render_url,
            headers=headers,
            json=request_body,
            timeout=(20, max(120, int(os.getenv("WORKFLOW_RENDER_TIMEOUT_SECONDS") or 2400))),
        )
    except requests.RequestException as exc:
        raise ProviderError("render_unavailable", "视频渲染服务暂时不可用") from exc
    if response.status_code >= 400:
        raise ProviderError("render_failed", "视频渲染失败，服务响应异常")
    logger.info(
        "render_request_finished job_id=%s workflow=%s status=%s",
        job["id"],
        job["workflow_code"],
        response.status_code,
    )
    append_job_log(job["id"], "视频已生成，正在回传文件")
    try:
        rendered = _extract_results(response.json(), "video")
    except ValueError as exc:
        raise ProviderError("render_failed", "视频渲染服务返回了无效响应") from exc
    videos = [result for result in rendered if result["type"] == "video"]
    if not videos:
        raise ProviderError("render_failed", "视频渲染完成但没有返回 MP4 地址")
    hosted_videos = []
    max_bytes = max(1, int(os.getenv("WORKFLOW_RENDER_MAX_VIDEO_BYTES") or 4 * 1024 * 1024 * 1024))
    for index, video in enumerate(videos, start=1):
        destination = RESULT_DIR / f"{job['workflow_code'].lower()}-{job['id']}-{index}.mp4"
        temporary = destination.with_suffix(".mp4.download")
        temporary.unlink(missing_ok=True)
        download = None
        try:
            download = requests.get(
                video["url"],
                stream=True,
                timeout=(20, max(120, int(os.getenv("WORKFLOW_RENDER_DOWNLOAD_TIMEOUT_SECONDS") or 1800))),
            )
            if download.status_code >= 400:
                raise ProviderError("render_download_failed", "视频回传失败，服务响应异常")
            content_length = int(download.headers.get("Content-Length") or 0)
            if content_length > max_bytes:
                raise ProviderError("render_download_failed", "剪映视频超过主站允许的最大文件大小")
            written = 0
            RESULT_DIR.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as stream:
                for block in download.iter_content(chunk_size=1024 * 1024):
                    if not block:
                        continue
                    written += len(block)
                    if written > max_bytes:
                        raise ProviderError("render_download_failed", "剪映视频超过主站允许的最大文件大小")
                    stream.write(block)
            if written <= 0:
                raise ProviderError("render_download_failed", "渲染机返回了空的视频文件")
            temporary.replace(destination)
        except ProviderError:
            raise
        except (OSError, ValueError, requests.RequestException) as exc:
            raise ProviderError("render_download_failed", "剪映视频无法回传到主站") from exc
        finally:
            temporary.unlink(missing_ok=True)
            if download is not None:
                download.close()
        hosted_videos.append(
            {
                "type": "video",
                "url": f"/api/v1/job-results/{destination.name}",
                "poster_url": video.get("poster_url"),
                "downloadable": True,
            }
        )
    return [result for result in results if result["type"] != "draft"] + hosted_videos


def _load_draft_key_result(results: list[dict]) -> dict[str, Any] | None:
    for result in results:
        if result.get("type") != "draft" or result.get("format") != "draft_key":
            continue
        result_name = Path(str(result.get("url") or "")).name
        candidate = (RESULT_DIR / result_name).resolve()
        if RESULT_DIR.resolve() not in candidate.parents or not candidate.is_file():
            raise ProviderError("draft_key_missing", "后台生成的视频草稿文件不存在")
        try:
            draft_key = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProviderError("invalid_draft_key", "后台生成的视频草稿文件无法读取") from exc
        return draft_key
    return None


def _queue_device_render(job: dict, results: list[dict]) -> None:
    if _load_draft_key_result(results) is None:
        raise ProviderError("draft_key_missing", "任务没有可发送给本机导出助手的视频草稿")
    _update_job(
        job["id"],
        status="rendering",
        stage="waiting_for_device",
        progress=78,
        results_json=json.dumps(results, ensure_ascii=False),
        render_claimed_at=None,
        error_code=None,
        error_message=None,
    )
    append_job_log(job["id"], "视频草稿已加入本机导出队列，等待导出助手领取")


def claim_device_render_job(device_id: str, lease_seconds: int = 600) -> dict | None:
    """Atomically lease one waiting job explicitly assigned to this device.

    The job owner may differ from the device owner when an administrator shares
    one rendering computer with ordinary site users.
    """
    now = time.time()
    expired = now - max(60, int(lease_seconds))
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT id FROM jobs
               WHERE render_device_id = ? AND status = 'rendering'
                 AND (stage = 'waiting_for_device'
                      OR (stage LIKE 'device_%' AND COALESCE(render_claimed_at, 0) < ?))
               ORDER BY created_at LIMIT 1""",
            (device_id, expired),
        ).fetchone()
        if not row:
            db.commit()
            return None
        db.execute(
            """UPDATE jobs SET stage = 'device_preparing', progress = 82,
               render_claimed_at = ?, updated_at = ? WHERE id = ?""",
            (now, now, row["id"]),
        )
        db.commit()
    job = get_job(row["id"])
    if not job:
        return None
    logger.info(
        "device_render_claimed job_id=%s device_id=%s",
        job["id"],
        device_id,
    )
    append_job_log(job["id"], "本机导出助手已领取任务，正在接收草稿数据")
    draft_key = _load_draft_key_result(job["results"])
    if draft_key is None:
        fail_device_render_job(job["id"], device_id, "draft_key_missing", "后台任务缺少 draft_key")
        return None
    return {
        "job_id": job["id"],
        "workflow_code": job["workflow_code"],
        "draft_key": draft_key,
        "recover_local_after": job["inputs"].get("_recover_local_after"),
    }


_DEVICE_PROGRESS_STAGES = {
    "device_preparing",
    "device_importing",
    "device_draft_ready",
    "device_preparing_resources",
    "device_opening_jianying",
    "device_exporting",
    "device_uploading",
}

_DEVICE_PROGRESS_STAGE_RANK = {
    "device_preparing": 0,
    "device_importing": 1,
    "device_draft_ready": 2,
    "device_preparing_resources": 3,
    "device_opening_jianying": 4,
    "device_exporting": 5,
    "device_uploading": 6,
}


def report_device_render_progress(
    job_id: str,
    device_id: str,
    *,
    stage: str,
    progress: int,
    message: str = "",
) -> bool:
    """Persist a truthful milestone reported by the paired Windows helper."""
    job = get_job(job_id)
    normalized_stage = str(stage or "").strip()
    if (
        not job
        or job.get("render_device_id") != device_id
        or job["status"] != "rendering"
        or normalized_stage not in _DEVICE_PROGRESS_STAGES
    ):
        return False
    current_progress = int(job.get("progress") or 0)
    normalized_progress = max(current_progress, min(99, max(82, int(progress))))
    current_stage = str(job.get("stage") or "")
    if _DEVICE_PROGRESS_STAGE_RANK.get(normalized_stage, -1) < _DEVICE_PROGRESS_STAGE_RANK.get(
        current_stage, -1
    ):
        normalized_stage = current_stage
    _update_job(
        job_id,
        stage=normalized_stage,
        progress=normalized_progress,
        render_claimed_at=time.time(),
    )
    if str(message or "").strip():
        append_job_log(job_id, message)
    return True


def complete_device_render_job(
    job_id: str,
    device_id: str,
    result_name: str = "",
    *,
    result_url: str = "",
) -> bool:
    job = get_job(job_id)
    if not job or job.get("render_device_id") != device_id or job["status"] != "rendering":
        return False
    hosted_url = str(result_url or "").strip()
    if not hosted_url:
        hosted_url = f"/api/v1/job-results/{Path(result_name).name}"
    results = [
        {
            "type": "video",
            "url": hosted_url,
            "poster_url": None,
            "downloadable": True,
        }
    ]
    _update_job(
        job_id,
        status="succeeded",
        stage="completed",
        progress=100,
        results_json=json.dumps(results, ensure_ascii=False),
        error_code=None,
        error_message=None,
    )
    append_job_log(job_id, "视频导出完成，已回传到站点")
    return True


def promote_device_render_result(
    job_id: str,
    result_name: str,
    result_url: str,
    download_url: str = "",
    preview_1080_url: str = "",
) -> bool:
    """Replace a completed job's local video URL after background delivery."""

    job = get_job(job_id)
    hosted_url = str(result_url or "").strip()
    if not job or job.get("status") != "succeeded" or not hosted_url:
        return False
    local_url = f"/api/v1/job-results/{Path(result_name).name}"
    results = list(job.get("results") or [])
    changed = False
    for result in results:
        if result.get("type") != "video":
            continue
        current_url = str(result.get("url") or "")
        if current_url == hosted_url:
            return True
        if current_url == local_url:
            result["url"] = hosted_url
            if str(download_url or "").strip():
                result["download_url"] = str(download_url).strip()
            if str(preview_1080_url or "").strip():
                result["preview_1080_url"] = str(preview_1080_url).strip()
            changed = True
    if not changed:
        return False
    _update_job(job_id, results_json=json.dumps(results, ensure_ascii=False))
    return True


def delete_job_video_results(job_id: str) -> bool:
    """Remove local video files and clear video links while preserving job history."""
    job = get_job(job_id)
    if not job or job.get("status") != "succeeded":
        return False
    results = list(job.get("results") or [])
    retained = []
    removed = False
    for result in results:
        if result.get("type") != "video":
            retained.append(result)
            continue
        removed = True
        for raw_url in {str(result.get("url") or ""), str(result.get("download_url") or "")}:
            prefix = "/api/v1/job-results/"
            if not raw_url.startswith(prefix):
                continue
            local_path = get_result_path(Path(raw_url.removeprefix(prefix)).name)
            if local_path:
                local_path.unlink(missing_ok=True)
    if not removed:
        return False
    _update_job(
        job_id,
        stage="video_deleted",
        results_json=json.dumps(retained, ensure_ascii=False),
    )
    append_job_log(job_id, "用户已删除云端视频，存储空间已经释放")
    return True


def fail_device_render_job(job_id: str, device_id: str, code: str, message: str) -> bool:
    job = get_job(job_id)
    if not job or job.get("render_device_id") != device_id or job["status"] != "rendering":
        return False
    normalized_code = str(code or "device_render_failed")[:80]
    normalized_message = str(message or "本机剪映导出失败")[:2000]
    logger.warning(
        "device_render_failed job_id=%s device_id=%s code=%s message=%r",
        job_id,
        device_id,
        normalized_code,
        normalized_message,
    )
    _update_job(
        job_id,
        status="failed",
        stage="failed",
        progress=100,
        error_code=normalized_code,
        error_message=normalized_message,
    )
    append_job_log(job_id, f"本机视频导出失败：{normalized_message}", level="error")
    return True


def _run_demo(job: dict) -> list[dict]:
    _update_job(job["id"], stage="generating", progress=45)
    code = job["workflow_code"]
    if code == "G247":
        asset_ids = job["inputs"].get("image") or []
        if not isinstance(asset_ids, list):
            asset_ids = [asset_ids]
        return [
            {"type": "image", "url": f"/api/v1/assets/{asset_id}", "poster_url": None, "downloadable": True}
            for asset_id in asset_ids
        ]
    if code == "G218":
        return [{"type": "image", "url": "/api/v1/demo/G218/result", "poster_url": None, "downloadable": True}]
    if code == "G159":
        return [{
            "type": "video",
            "url": "/api/v1/demo/G159/result",
            "poster_url": "/api/v1/workflows/G159/preview?category=减肥",
            "downloadable": True,
        }]
    raise ProviderError("provider_not_configured", "该工作流正在接入后台生成服务")


def _run_local_workflow(job: dict) -> list[dict]:
    """Generate one of this repository's own importable workflow files."""
    _update_job(job["id"], stage="building_workflow", progress=45)
    code = job["workflow_code"]
    inputs = job["inputs"]
    if code in LOCAL_CODES:
        return _save_local_draft_key_result(job, _build_local_draft_key(job))
    destination = RESULT_DIR / f"{code.lower()}-{job['id']}.json"
    generated_destination = destination

    if code == "OWN02":
        from workflows.cigarette import generate_cigarette_workflow
        from workflows.draft_key_recorder import add_draft_key_recorder

        workflow, _warning = generate_cigarette_workflow(
            str(inputs.get("theme") or inputs.get("cigarette_name") or "").strip(),
            cover_url=str(inputs.get("cover_url") or "").strip(),
            voice_id=str(inputs.get("voice_id") or "").strip(),
        )
        add_draft_key_recorder(
            workflow,
            workflow_name="香烟工作流_米核插件+draft_key记录",
            draft_name=f"香烟_{str(inputs.get('theme') or inputs.get('cigarette_name') or '').strip()}",
            run_prefix="cigarette_recorded_",
        )
        destination.write_text(json.dumps(workflow, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        if code == "OWN01":
            generated_destination = destination.with_name(f".{destination.name}.source.json")
            command = [
                "node",
                str(ROOT / "generate-book-template.js"),
                str(inputs.get("theme") or inputs.get("book_name") or "").strip(),
                "--out",
                str(generated_destination),
            ]
            option_map = {
                "author": "--author",
                "visual_style": "--desc",
                "book_script": "--cankao",
                "scene_count": "--shuliang",
                "voice_id": "--yinse",
            }
        elif code == "OWN03":
            generated_destination = destination.with_name(f".{destination.name}.source.json")
            command = [
                "node",
                str(ROOT / "generate-god-template.js"),
                str(inputs.get("theme") or inputs.get("god_name") or "").strip(),
                "--out",
                str(generated_destination),
            ]
            option_map = {
                "description": "--desc",
                "script": "--wenan",
                "scene_count": "--shuliang",
                "audio_url": "--audio",
                "voice_id": "--yinse",
            }
        else:  # pragma: no cover - registry prevents this branch
            raise ProviderError("local_workflow_not_found", "本地工作流不存在")

        for input_name, flag in option_map.items():
            value = inputs.get(input_name)
            if value not in (None, ""):
                command.extend([flag, str(value)])
        try:
            process = subprocess.run(
                command,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            generated_destination.unlink(missing_ok=True)
            raise ProviderError("local_generator_failed", "本地工作流生成器无法运行") from exc
        if process.returncode != 0 or not generated_destination.is_file():
            detail = (process.stderr or process.stdout or "").strip()[-300:]
            generated_destination.unlink(missing_ok=True)
            raise ProviderError("local_generator_failed", detail or "本地工作流生成失败")

        if code in {"OWN01", "OWN03"}:
            from workflows.draft_key_recorder import generate_recorded_workflow

            theme = str(inputs.get("theme") or "").strip()
            profile = {
                "OWN01": ("书单工作流_米核插件+draft_key记录", f"书单_{theme}", "book_recorded_"),
                "OWN03": ("神工作流_米核插件+draft_key记录", f"神话解说_{theme}", "god_recorded_"),
            }[code]
            try:
                generate_recorded_workflow(
                    generated_destination,
                    destination,
                    workflow_name=profile[0],
                    draft_name=profile[1],
                    run_prefix=profile[2],
                )
            except Exception as exc:
                destination.unlink(missing_ok=True)
                raise ProviderError("local_generator_failed", f"生成视频草稿失败: {exc}") from exc
            finally:
                generated_destination.unlink(missing_ok=True)

    if not destination.is_file():
        raise ProviderError("local_generator_failed", "本地工作流没有生成结果文件")
    return [
        {
            "type": "draft",
            "url": f"/api/v1/job-results/{destination.name}",
            "poster_url": None,
            "downloadable": True,
        }
    ]


def _run_reference_template(job: dict) -> list[dict]:
    """Personalize a downloaded Coze clipboard workflow with one topic."""
    _update_job(job["id"], stage="building_workflow", progress=45)
    code = job["workflow_code"]
    theme = str(job["inputs"].get("theme") or "").strip()
    source = next(
        (
            item["path"]
            for item in find_workflow_downloads(job["category"], code)
            if item["kind"] == "json"
        ),
        None,
    )
    if not source:
        raise ProviderError("workflow_template_missing", "工作流母版文件不存在")
    try:
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
        nodes = (payload.get("json") or {}).get("nodes") or []
        start = next(node for node in nodes if str(node.get("type")) == "1")
        outputs = (start.get("data") or {}).get("outputs") or []
    except (OSError, ValueError, StopIteration) as exc:
        raise ProviderError("workflow_template_invalid", "工作流母版缺少有效开始节点") from exc

    values_by_code = {
        "G259": {"biaoti": theme},
        "G258": {"biaoti": theme},
        "G168": {"text": theme},
        "G45": {"title": theme},
        "G263": {"subject": theme, "name": theme},
        "G129": {"theme": theme},
        "G159": {"title": theme, "left_text": "自律", "right_text": "坚持"},
        "G222": {"business": theme, "kaichang": f"{theme}，它的商业模式到底是什么？"},
    }
    replacements = values_by_code.get(code) or {}
    changed = set()
    for output in outputs:
        name = str(output.get("name") or "")
        if name in replacements:
            output["defaultValue"] = replacements[name]
            changed.add(name)
    if changed != set(replacements):
        raise ProviderError("workflow_template_invalid", "工作流母版主题字段与预期不一致")

    destination = RESULT_DIR / f"{code.lower()}-{job['id']}.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return [
        {
            "type": "draft",
            "url": f"/api/v1/job-results/{destination.name}",
            "poster_url": None,
            "downloadable": True,
        }
    ]


init_database()
