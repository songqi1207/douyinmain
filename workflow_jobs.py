"""SQLite-backed workflow jobs, assets, and provider execution."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from business_workflows import find_workflow_downloads
from workflow_registry import LOCAL_CODES, REFERENCE_TEMPLATE_CODES, get_workflow, published_workflow_id


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("WORKFLOW_DATA_DIR") or ROOT / "temp" / "workflow_app").resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
DB_PATH = Path(os.getenv("WORKFLOW_DB_PATH") or DATA_DIR / "workflow.sqlite3").resolve()
MAX_UPLOAD_BYTES = int(os.getenv("WORKFLOW_MAX_UPLOAD_BYTES") or 100 * 1024 * 1024)

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
                user_id TEXT,
                cost_cents INTEGER NOT NULL DEFAULT 0,
                price_cents INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
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


def create_job(workflow_code: str, category: str, inputs: dict, user_id: str | None = None) -> dict:
    workflow = get_workflow(workflow_code, category)
    if not workflow:
        raise KeyError("workflow_not_found")
    if workflow["status"] != "online":
        raise PermissionError("workflow_not_online")
    validate_inputs(workflow, inputs)
    now = time.time()
    job_id = uuid.uuid4().hex
    with _connect() as db:
        db.execute(
            """INSERT INTO jobs
            (id, workflow_code, category, status, stage, progress, inputs_json, results_json,
             error_code, error_message, user_id, cost_cents, price_cents, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', 'queued', 0, ?, '[]', NULL, NULL, ?, 0, 0, ?, ?)""",
            (job_id, workflow_code.upper(), category, json.dumps(inputs, ensure_ascii=False), user_id, now, now),
        )
        db.commit()
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


def list_jobs(user_id: str, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
    """Return newest jobs without exposing their submitted input payloads."""
    offset = (page - 1) * page_size
    with _connect() as db:
        total = int(db.execute("SELECT COUNT(*) FROM jobs WHERE user_id = ?", (user_id,)).fetchone()[0])
        rows = db.execute(
            "SELECT id FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, page_size, offset),
        ).fetchall()
    return [job for row in rows if (job := get_job(row["id"]))], total


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
    allowed = {"status", "stage", "progress", "results_json", "error_code", "error_message", "cost_cents", "price_cents"}
    values = {key: value for key, value in changes.items() if key in allowed}
    values["updated_at"] = time.time()
    assignments = ", ".join(f"{key} = ?" for key in values)
    with _connect() as db:
        db.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*values.values(), job_id))
        db.commit()


def enqueue_job(job_id: str, background_tasks=None):
    mode = (os.getenv("WORKFLOW_QUEUE_MODE") or "inline").strip().lower()
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
        return
    try:
        _update_job(job_id, status="running", stage="preparing", progress=10)
        mode = (os.getenv("WORKFLOW_PROVIDER_MODE") or "demo").strip().lower()
        build_mode = (os.getenv("WORKFLOW_BUILD_MODE") or "template").strip().lower()
        published_local = (
            job["workflow_code"] in LOCAL_CODES
            and bool((os.getenv("COZE_API_TOKEN") or "").strip())
            and bool(published_workflow_id(job["workflow_code"]))
        )
        if published_local:
            results = _run_coze(job)
        elif job["workflow_code"] in LOCAL_CODES:
            results = _run_local_workflow(job)
        elif job["workflow_code"] in REFERENCE_TEMPLATE_CODES and build_mode == "template":
            results = _run_reference_template(job)
        elif mode == "coze":
            results = _run_coze(job)
        else:
            results = _run_demo(job)
        workflow = get_workflow(job["workflow_code"], job["category"]) or {}
        if (
            workflow.get("generation_mode") != "workflow_template"
            and any(result["type"] == "draft" for result in results)
        ):
            results = _render_drafts(job, results)
        cost_cents = int(os.getenv(f"WORKFLOW_COST_CENTS_{job['workflow_code']}") or 0)
        price_cents = int(os.getenv(f"WORKFLOW_PRICE_CENTS_{job['workflow_code']}") or 0)
        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            progress=100,
            results_json=json.dumps(results, ensure_ascii=False),
            cost_cents=cost_cents,
            price_cents=price_cents,
        )
    except ProviderError as exc:
        _update_job(job_id, status="failed", stage="failed", progress=100, error_code=exc.code, error_message=str(exc))
    except Exception as exc:
        _update_job(job_id, status="failed", stage="failed", progress=100, error_code="internal_error", error_message=str(exc))


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _asset_public_url(asset_id: str) -> str:
    base = (os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/v1/assets/{asset_id}"


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
    if code == "OWN03":
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
        if os.getenv(env_name):
            result[parameter] = os.getenv(env_name)
    return result


def _run_coze(job: dict) -> list[dict]:
    token = (os.getenv("COZE_API_TOKEN") or "").strip()
    workflow_id = published_workflow_id(job["workflow_code"])
    if not token or not workflow_id:
        raise ProviderError("provider_not_configured", "扣子工作流尚未发布或后台 Token 未配置")
    _update_job(job["id"], stage="generating", progress=35)
    response = requests.post(
        (os.getenv("COZE_API_BASE_URL") or "https://api.coze.cn").rstrip("/") + "/v1/workflow/run",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"workflow_id": workflow_id, "parameters": _provider_inputs(job["inputs"], job["workflow_code"])},
        timeout=(20, 900),
    )
    if response.status_code == 429:
        raise ProviderError("provider_rate_limited", "扣子服务繁忙，请稍后重试")
    if response.status_code >= 400:
        raise ProviderError("provider_error", f"扣子执行失败（HTTP {response.status_code}）")
    payload = response.json()
    if payload.get("code") not in (None, 0):
        raise ProviderError("provider_error", str(payload.get("msg") or payload.get("message") or "扣子执行失败"))
    data = _decode_nested_json(payload.get("data"))
    if job["workflow_code"] in LOCAL_CODES:
        return _save_draft_key_result(job, data)
    workflow = get_workflow(job["workflow_code"], job["category"]) or {}
    results = _extract_results(data, workflow.get("output_type", "draft"))
    if not results:
        raise ProviderError("empty_result", "工作流执行完成但没有可展示结果")
    return results


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


def _save_draft_key_result(job: dict, data: Any) -> list[dict]:
    draft_key = _decode_nested_json(_find_nested_field(data, "draft_key"))
    if draft_key is None and isinstance(data, dict) and isinstance(data.get("calls"), list):
        draft_key = data
    if not isinstance(draft_key, dict):
        raise ProviderError("draft_key_missing", "扣子工作流已完成，但返回结果中没有 draft_key")

    from utils.draft_key_importer import KeyValidationError, import_draft_key

    try:
        import_draft_key(draft_key, dry_run=True)
    except KeyValidationError as exc:
        raise ProviderError("invalid_draft_key", "扣子返回的 draft_key 校验失败：" + "；".join(exc.errors)) from exc

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    destination = RESULT_DIR / f"{job['workflow_code'].lower()}-{job['id']}-draft-key.json"
    destination.write_text(json.dumps(draft_key, ensure_ascii=False, indent=2), encoding="utf-8")
    remote_draft_id = _find_nested_field(data, "draft_id")
    _update_job(job["id"], stage="draft_key_ready", progress=75)
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
    headers = {"Content-Type": "application/json"}
    if render_token:
        headers["Authorization"] = f"Bearer {render_token}"
    draft_key = None
    for result in results:
        if result.get("type") != "draft" or result.get("format") != "draft_key":
            continue
        result_name = Path(str(result.get("url") or "")).name
        candidate = (RESULT_DIR / result_name).resolve()
        if RESULT_DIR.resolve() not in candidate.parents or not candidate.is_file():
            raise ProviderError("draft_key_missing", "后台生成的 draft_key 文件不存在")
        try:
            draft_key = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProviderError("invalid_draft_key", "后台生成的 draft_key 文件无法读取") from exc
        break

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
        raise ProviderError("render_failed", f"视频渲染失败（HTTP {response.status_code}）")
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
                raise ProviderError("render_download_failed", f"剪映视频回传失败（HTTP {download.status_code}）")
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
                raise ProviderError("local_generator_failed", f"生成 draft_key 工作流失败: {exc}") from exc
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
