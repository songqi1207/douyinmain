"""FastAPI entrypoint for the React workflow center."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
import uuid
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from business_workflows import find_preview_asset, find_workflow_downloads
from direct_upload_tokens import create_direct_upload_token
from desktop_bridge.helper_metadata import (
    HELPER_BINARY_NAME,
    HELPER_DOWNLOAD_NAME,
    HELPER_PRODUCT_NAME,
    HELPER_VERSION,
)
from device_rendering import (
    authenticate_device,
    create_pairing_code,
    heartbeat_device,
    list_devices,
    pair_device,
    preferred_device,
    revoke_device,
)
from site_accounts import (
    QuotaError,
    PREVIEW_1080_UNLOCK_POINTS,
    SESSION_TTL_SECONDS,
    active_admin_user,
    adjust_user_quota,
    authenticate_user,
    change_user_password,
    complete_registration_approval,
    create_session,
    delete_session,
    fail_registration_delivery,
    favorite_ids,
    list_registration_applications,
    list_user_quotas,
    mark_video_storage_deleted,
    prepare_registration_approval,
    provider_usage_snapshot,
    reveal_user_password,
    record_resource_event,
    record_video_storage,
    reject_registration_application,
    resource_stats,
    reserve_generation,
    reset_user_password_for_admin,
    quota_snapshot,
    site_account_summary,
    submit_registration_application,
    settle_generation_reservation,
    toggle_favorite,
    unlock_video_preview,
    update_workflow_pricing,
    user_from_session,
    verify_user_password,
    workflow_pricing_snapshot,
)
from workflow_catalog import IMAGE_WORKFLOWS, workflow_categories
from workflow_jobs import (
    DRAFT_KEY_RENDER_CODE,
    RESULT_DIR,
    append_job_log,
    claim_device_render_job,
    clear_active_jobs,
    complete_device_render_job,
    create_asset,
    create_draft_key_render_job,
    create_job,
    delete_job_video_results,
    enqueue_job,
    fail_device_render_job,
    get_asset,
    get_job,
    get_job_logs,
    get_result_path,
    job_summary,
    list_jobs,
    list_admin_jobs,
    promote_device_render_result,
    report_device_render_progress,
    user_can_access_result,
    workflow_job_counts,
)
from workflow_registry import (
    PUBLISHED_WORKFLOW_ENV_ALIASES,
    WORKFLOW_INPUT_DEFAULTS_ENV,
    category_summary,
    configured_workflow_input_defaults,
    get_workflow,
    list_workflows,
    published_workflow_id,
    runtime_input_schema,
)
from health_checks import latest_health_check, run_health_check, start_health_scheduler
from utils.draft_key_importer import KeyValidationError
from utils.email_delivery import (
    EmailConfigurationError,
    email_delivery_status,
    send_registration_application_received,
    send_registration_approved,
)
from utils.local_media_generation import generated_file_path, list_system_voices, synthesize_speech
from utils.runtime_settings import update_dotenv_file
from video_delivery import VideoDeliveryError, delete_video_from_r2, publish_device_video, r2_export_configured
from utils.volcengine_vod_renderer import (
    VodConfigurationError,
    VodRenderError,
    VolcengineVodRenderer,
    render_draft_key_vod,
)


ROOT = Path(__file__).resolve().parent
logger = logging.getLogger("workflow.api")
RUNTIME_ENV_PATH = ROOT / ".env"
JIANYING_COMPAT_VERSION = "5.9.0.11632"
MINIMUM_RENDER_HELPER_VERSION = "1.4.87"
DEVICE_UPLOAD_PART_MAX_BYTES = 40 * 1024 * 1024


def _helper_version_at_least(version: str, minimum: str) -> bool:
    try:
        current = tuple(int(part) for part in str(version).split("."))
        required = tuple(int(part) for part in str(minimum).split("."))
    except (TypeError, ValueError):
        return False
    width = max(len(current), len(required))
    return current + (0,) * (width - len(current)) >= required + (0,) * (width - len(required))
JIANYING_COMPAT_DOWNLOAD_URL = (
    os.getenv("JIANYING_COMPAT_DOWNLOAD_URL") or
    "https://lf3-package.vlabstatic.com/obj/faceu-packages/"
    "Jianying_5_9_0_11632_jianyingpro_0_creatortool.exe"
).strip()
JIANYING_COMPAT_SHA256 = (
    "C0919B9A6D499FB8659DE3D314D25B10"
    "C7892F9072CB3AD00BEF62A89D13E399"
)
FRONTEND_DIST = ROOT / "frontend" / "dist"
SESSION_COOKIE = "workflow_session"

app = FastAPI(title="工作流中心", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in (os.getenv("CORS_ORIGINS") or "*").split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Vite assets before the SPA catch-all route so hashed JS/CSS files are
# served as files instead of receiving index.html.
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/business/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="business-assets")


@app.on_event("startup")
def _start_daily_health_checks() -> None:
    start_health_scheduler()


def _spa_index() -> FileResponse | HTMLResponse:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(
            index,
            media_type="text/html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>工作流中心</title>
</head>
<body style="margin:0;background:#111;color:#f5f5f5;font-family:system-ui,'Microsoft YaHei',sans-serif;display:grid;min-height:100vh;place-items:center">
  <main style="max-width:560px;padding:32px;line-height:1.7">
    <h1 style="margin:0 0 12px">前端资源未构建</h1>
    <p>请在部署镜像中执行 <code>npm ci && npm run build</code>，或使用仓库 Dockerfile 构建。</p>
  </main>
</body>
</html>
        """.strip()
    )


def _request_user(request: Request) -> dict | None:
    return user_from_session(request.cookies.get(SESSION_COOKIE))


def _require_user(request: Request) -> dict:
    user = _request_user(request)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "login_required", "message": "请先登录"})
    return user


def _require_ready_user(request: Request) -> dict:
    user = _require_user(request)
    if user.get("must_change_password"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "password_change_required",
                "message": "请先修改邮件中的临时密码",
            },
        )
    return user


def _require_admin(request: Request) -> dict:
    user = _require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "仅管理员可以审核注册申请"})
    return user


def _preferred_render_device(user: dict) -> tuple[dict | None, bool]:
    """Select the user's own device, then the administrator's shared device."""
    own_device = preferred_device(user["id"])
    if own_device or user.get("role") == "admin":
        return own_device, False
    admin = active_admin_user()
    shared_device = preferred_device(admin["id"]) if admin else None
    return shared_device, bool(shared_device)


def _reserve_job_quota(user: dict, job_id: str, workflow_code: str) -> dict:
    pricing = workflow_pricing_snapshot(workflow_code)
    try:
        reserve_generation(user["id"], job_id, pricing["price_points"])
    except QuotaError as exc:
        code = str(exc)
        messages = {
            "generation_quota_exhausted": "平台积分不足，请联系管理员充值或邀请新用户获得积分",
            "storage_quota_exhausted": "视频云存储空间已满，请先删除旧视频或联系管理员扩容",
        }
        raise HTTPException(
            status_code=402,
            detail={"code": code, "message": messages.get(code, "当前账号积分不足")},
        ) from exc
    return pricing


def _require_render_device(request: Request) -> dict:
    authorization = str(request.headers.get("authorization") or "")
    scheme, _, token = authorization.partition(" ")
    device = authenticate_device(token if scheme.lower() == "bearer" else "")
    if not device:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_device_token", "message": "本机剪映助手尚未配对或授权已失效"},
        )
    return device


def _runtime_settings_payload() -> dict:
    workflows = sorted(list_workflows(), key=lambda item: str(item.get("code") or ""))
    mihe_key = (os.getenv("MIHE_KEY") or "").strip()
    workflow_input_defaults = configured_workflow_input_defaults()
    return {
        "mihe_key": {
            "configured": bool(mihe_key),
            "masked": f"••••{mihe_key[-4:]}" if mihe_key else "",
        },
        "workflows": [
            {
                "code": str(item.get("code") or "").upper(),
                "name": str(item.get("name") or item.get("code") or ""),
                "category": str(item.get("category") or ""),
                "workflow_id": published_workflow_id(str(item.get("code") or "")),
                "input_schema": runtime_input_schema(item),
                "input_defaults": deepcopy(
                    workflow_input_defaults.get(str(item.get("code") or "").upper(), {})
                ),
            }
            for item in workflows
            if item.get("code")
        ],
    }


_SENSITIVE_WORKFLOW_INPUT = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|token|secret|password|mihe[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)


def _normalize_workflow_input_defaults(
    payload: object,
    known_codes: set[str],
) -> dict[str, dict]:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_workflow_inputs", "message": "工作流输入参数配置必须是对象"},
        )
    normalized: dict[str, dict] = {}
    for raw_code, raw_values in payload.items():
        code = str(raw_code or "").upper().strip()
        if code not in known_codes:
            raise HTTPException(
                status_code=422,
                detail={"code": "unknown_workflow_code", "message": f"未知工作流：{code or '<empty>'}"},
            )
        if not isinstance(raw_values, dict):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_workflow_inputs", "message": f"{code} 的输入参数必须是 JSON 对象"},
            )
        if len(raw_values) > 60:
            raise HTTPException(
                status_code=422,
                detail={"code": "too_many_workflow_inputs", "message": f"{code} 最多配置 60 个输入参数"},
            )
        values: dict[str, object] = {}
        for raw_name, value in raw_values.items():
            name = str(raw_name or "").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,127}", name):
                raise HTTPException(
                    status_code=422,
                    detail={"code": "invalid_workflow_input_name", "message": f"{code} 的参数名“{name}”格式不正确"},
                )
            if _SENSITIVE_WORKFLOW_INPUT.search(name):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "sensitive_workflow_input",
                        "message": f"{code} 的参数“{name}”属于密钥类参数，请使用专门的 Key 配置项",
                    },
                )
            values[name] = value
        normalized[code] = values
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 128 * 1024:
        raise HTTPException(
            status_code=422,
            detail={"code": "workflow_inputs_too_large", "message": "工作流输入参数配置不能超过 128KB"},
        )
    return normalized


def _request_event_key(request: Request, resource_id: str, event_type: str) -> str:
    user = _request_user(request)
    actor = user["id"] if user else "|".join(
        [request.client.host if request.client else "unknown", request.headers.get("user-agent", "unknown")]
    )
    bucket = int(time.time() // 1800) if event_type == "view" else time.time_ns()
    return hashlib.sha256(f"{actor}|{resource_id}|{event_type}|{bucket}".encode("utf-8")).hexdigest()


def _workflow_stats(items: list[dict]) -> list[dict]:
    counts = resource_stats("workflow", [item["code"] for item in items])
    runs = workflow_job_counts([item["code"] for item in items])
    result = []
    for item in items:
        public_item = deepcopy(item)
        public_item["stats"] = counts.get(
            item["code"], {"views": 0, "favorites": 0, "downloads": 0, "runs": 0}
        )
        public_item["stats"]["runs"] = runs.get(item["code"], 0)
        pricing = workflow_pricing_snapshot(item["code"])
        public_item["pricing"] = {
            "workflow_code": pricing["workflow_code"],
            "price_points": pricing["price_points"],
        }
        result.append(public_item)
    return result


def _normalize_configured_voice(row: dict) -> dict | None:
    voice_id = str(row.get("id") or row.get("voice_id") or "").strip()
    if not voice_id:
        return None
    gender = str(row.get("gender") or "neutral").lower()
    if gender not in {"female", "male", "boy", "girl", "neutral"}:
        gender = "neutral"
    return {
        "id": voice_id,
        "name": str(row.get("name") or voice_id).strip(),
        "gender": gender,
        "gender_label": str(row.get("gender_label") or {"female": "女声", "male": "男声", "boy": "男童", "girl": "女童", "neutral": "中性"}[gender]),
        "language": str(row.get("language") or "未标注").strip(),
        "description": str(row.get("description") or "已配置的云端配音音色").strip(),
        "model": str(row.get("model") or "cloud-tts").strip(),
        "provider": "external",
        "available": True,
    }


@lru_cache(maxsize=1)
def _voice_catalog_state() -> dict:
    provider_url = (os.getenv("TTS_API_URL") or "").strip()
    if provider_url:
        raw_catalog = (os.getenv("TTS_VOICES_JSON") or "").strip()
        try:
            rows = json.loads(raw_catalog) if raw_catalog else []
        except json.JSONDecodeError:
            rows = []
        if isinstance(rows, dict):
            rows = rows.get("voices") or []
        voices = [voice for row in rows if isinstance(row, dict) and (voice := _normalize_configured_voice(row))]
        return {
            "voices": voices,
            "provider": "external",
            "available": bool(voices),
            "message": "云端配音服务已连接" if voices else "云端 TTS 已配置，但尚未配置真实音色目录 TTS_VOICES_JSON",
        }
    voices = list_system_voices()
    return {
        "voices": voices,
        "provider": "local-system",
        "available": bool(voices),
        "message": "使用服务器实际安装的 Windows 音色" if voices else "服务器没有可用的 Windows System.Speech 音色，也未配置云端 TTS",
    }


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=(os.getenv("SITE_COOKIE_SECURE") or "").lower() in {"1", "true", "yes"},
        path="/",
    )


@app.get("/", include_in_schema=False)
def root_redirect(request: Request):
    query = request.url.query
    target = "/business/"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target)


@app.get("/business", include_in_schema=False)
def business_redirect(request: Request):
    query = request.url.query
    target = "/business/"
    if query:
        target = f"{target}?{query}"
    return RedirectResponse(target)


@app.get("/business/{path:path}", response_class=HTMLResponse, include_in_schema=False)
def business_spa_route(path: str):
    return _spa_index()


# ----------------------------- API v1 ---------------------------------


def _notify_admin_of_registration(application: dict) -> None:
    try:
        public_base = (os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        send_registration_application_received(
            str(application.get("email") or ""),
            f"{public_base}/business/admin/registrations",
        )
    except Exception:
        logger.exception("registration_application_notification_failed application_id=%s", application.get("id"))


@app.post("/api/v1/auth/register", status_code=202)
def api_register(background_tasks: BackgroundTasks, payload: dict = Body(default_factory=dict)):
    try:
        application = submit_registration_application(
            str(payload.get("email") or ""),
            str(payload.get("invite_code") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_registration", "message": str(exc)}) from exc
    if (os.getenv("REGISTRATION_NOTIFICATION_EMAIL") or "").strip():
        background_tasks.add_task(_notify_admin_of_registration, application)
    return {
        "application": application,
        "message": "申请已提交，管理员通过后登录密码会发送到该邮箱",
    }


@app.post("/api/v1/auth/login")
def api_login(response: Response, payload: dict = Body(default_factory=dict)):
    identifier = str(payload.get("email") or payload.get("username") or "")
    user = authenticate_user(identifier, str(payload.get("password") or ""))
    if not user:
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "用户名或密码错误"})
    _set_session_cookie(response, create_session(user["id"]))
    return {
        "user": user,
        "workflow_favorites": favorite_ids(user["id"], "workflow"),
        "voice_favorites": favorite_ids(user["id"], "voice"),
    }


@app.get("/api/v1/admin/registration-applications")
def api_registration_applications(request: Request, status: str = Query(default="pending")):
    _require_admin(request)
    try:
        applications = list_registration_applications(status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": str(exc)}) from exc
    return {
        "items": applications,
        "total": len(applications),
        "email_service": email_delivery_status(),
    }


@app.post("/api/v1/admin/registration-applications/{application_id}/approve")
def api_approve_registration(application_id: str, request: Request):
    admin = _require_admin(request)
    delivery = email_delivery_status()
    if not delivery["configured"]:
        raise HTTPException(status_code=503, detail={"code": "email_not_configured", "message": delivery["message"]})
    try:
        application, temporary_password = prepare_registration_approval(application_id, admin["id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "application_not_found", "message": "注册申请不存在"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "application_not_pending", "message": str(exc)}) from exc

    configured_base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    public_base = configured_base if configured_base and "your-domain.example.com" not in configured_base else f"{request.url.scheme}://{request.url.netloc}"
    try:
        send_registration_approved(application["email"], temporary_password, f"{public_base}/business/login")
        approved = complete_registration_approval(application_id)
    except (EmailConfigurationError, OSError, RuntimeError) as exc:
        fail_registration_delivery(application_id, str(exc))
        raise HTTPException(status_code=502, detail={"code": "email_delivery_failed", "message": f"审批邮件发送失败：{exc}"}) from exc
    return {"application": approved, "message": "审核已通过，登录密码已发送到用户邮箱"}


@app.post("/api/v1/admin/registration-applications/{application_id}/reject")
def api_reject_registration(application_id: str, request: Request):
    admin = _require_admin(request)
    try:
        application = reject_registration_application(application_id, admin["id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "application_not_found", "message": "注册申请不存在"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "application_already_reviewed", "message": str(exc)}) from exc
    return {"application": application, "message": "申请已拒绝"}


@app.get("/api/v1/admin/runtime-settings")
def api_admin_runtime_settings(request: Request):
    _require_admin(request)
    return _runtime_settings_payload()


@app.put("/api/v1/admin/runtime-settings")
def api_update_admin_runtime_settings(
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    _require_admin(request)
    updates: dict[str, str] = {}

    if payload.get("clear_mihe_key") is True:
        updates["MIHE_KEY"] = ""
    elif "mihe_key" in payload:
        mihe_key = str(payload.get("mihe_key") or "").strip()
        if mihe_key:
            if len(mihe_key) > 512:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "invalid_mihe_key", "message": "图片生成服务 Key 长度不能超过 512 个字符"},
                )
            updates["MIHE_KEY"] = mihe_key

    workflow_ids = payload.get("workflow_ids", {})
    if not isinstance(workflow_ids, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_workflow_ids", "message": "工作流 ID 配置格式不正确"},
        )

    known_codes = {str(item.get("code") or "").upper() for item in list_workflows()}
    for raw_code, raw_value in workflow_ids.items():
        code = str(raw_code or "").upper().strip()
        if code not in known_codes:
            raise HTTPException(
                status_code=422,
                detail={"code": "unknown_workflow_code", "message": f"未知工作流：{code or '<empty>'}"},
            )
        workflow_id = str(raw_value or "").strip()
        if workflow_id and not re.fullmatch(r"\d{8,32}", workflow_id):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_workflow_id", "message": f"{code} 的工作流 ID 应为 8–32 位数字"},
            )
        env_key = f"COZE_WORKFLOW_{code}"
        updates[env_key] = workflow_id
        alias = PUBLISHED_WORKFLOW_ENV_ALIASES.get(code)
        if alias:
            updates[alias] = workflow_id

    if "workflow_inputs" in payload:
        workflow_inputs = _normalize_workflow_input_defaults(
            payload.get("workflow_inputs"),
            known_codes,
        )
        updates[WORKFLOW_INPUT_DEFAULTS_ENV] = json.dumps(
            workflow_inputs,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    if updates:
        update_dotenv_file(RUNTIME_ENV_PATH, updates)
        for key, value in updates.items():
            os.environ[key] = value

    response = _runtime_settings_payload()
    response["message"] = "运行配置已保存并立即生效"
    return response


@app.post("/api/v1/auth/logout", status_code=204)
def api_logout(request: Request, response: Response):
    delete_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@app.post("/api/v1/auth/password")
def api_change_password(
    request: Request,
    response: Response,
    payload: dict = Body(default_factory=dict),
):
    user = _require_user(request)
    try:
        updated_user = change_user_password(
            user["id"],
            str(payload.get("current_password") or ""),
            str(payload.get("new_password") or ""),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "user_not_found", "message": "账号不存在"},
        ) from exc
    except ValueError as exc:
        code = str(exc)
        messages = {
            "new_password_length": "新密码需为 8–128 个字符",
            "password_reuse": "新密码不能与当前密码相同",
            "invalid_current_password": "当前密码不正确",
        }
        raise HTTPException(
            status_code=422,
            detail={"code": code, "message": messages.get(code, "密码修改失败")},
        ) from exc
    token = create_session(updated_user["id"])
    _set_session_cookie(response, token)
    return {
        "user": updated_user,
        "workflow_favorites": favorite_ids(updated_user["id"], "workflow"),
        "voice_favorites": favorite_ids(updated_user["id"], "voice"),
    }


@app.get("/api/v1/auth/me")
def api_me(request: Request):
    user = _request_user(request)
    if not user:
        return {"user": None, "workflow_favorites": [], "voice_favorites": []}
    return {
        "user": user,
        "workflow_favorites": favorite_ids(user["id"], "workflow"),
        "voice_favorites": favorite_ids(user["id"], "voice"),
    }


@app.post("/api/v1/favorites/{resource_type}")
def api_toggle_favorite(resource_type: str, request: Request, payload: dict = Body(default_factory=dict)):
    if resource_type not in {"workflow", "voice"}:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found", "message": "收藏类型不存在"})
    user = _require_user(request)
    resource_id = str(payload.get("resource_id") or "").strip()
    valid = bool(get_workflow(resource_id)) if resource_type == "workflow" else any(
        voice["id"] == resource_id for voice in _voice_catalog_state()["voices"]
    )
    if not valid:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found", "message": "收藏目标不存在"})
    try:
        selected = toggle_favorite(user["id"], resource_type, resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_favorite", "message": str(exc)}) from exc
    count = resource_stats(resource_type, [resource_id])[resource_id]["favorites"]
    return {"selected": selected, "resource_id": resource_id, "favorites": count}


@app.get("/api/v1/voices")
def api_voices():
    state = _voice_catalog_state()
    return {**state, "total": len(state["voices"])}


@app.get("/api/v1/site-summary")
def api_site_summary():
    workflows = list_workflows("全部")
    categories = category_summary()
    voice_state = _voice_catalog_state()
    accounts = site_account_summary()
    jobs = job_summary()
    accounts["runs"] = jobs["total"] + accounts["runs"]
    return {
        "catalog": {
            "workflows": len(workflows),
            "online_workflows": sum(item["status"] == "online" for item in workflows),
            "categories": len(categories),
            "voices": len(voice_state["voices"]),
        },
        "activity": accounts,
        "jobs": jobs,
        "voice_service": {
            "provider": voice_state["provider"],
            "available": voice_state["available"],
            "message": voice_state["message"],
        },
    }


@app.post("/api/v1/tts", status_code=201)
def api_tts(request: Request, payload: dict = Body(default_factory=dict)):
    user = _require_ready_user(request)
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail={"code": "missing_text", "message": "请输入配音文案"})
    if len(text) > 5000:
        raise HTTPException(status_code=422, detail={"code": "text_too_long", "message": "单次配音不能超过 5000 字"})
    voice_id = str(payload.get("voice_id") or "").strip()
    available_voice_ids = {voice["id"] for voice in _voice_catalog_state()["voices"]}
    if not voice_id or voice_id not in available_voice_ids:
        raise HTTPException(status_code=422, detail={"code": "invalid_voice", "message": "请选择服务器当前真实可用的音色"})
    provider_url = (os.getenv("TTS_API_URL") or "").strip()
    if provider_url:
        headers = {"Content-Type": "application/json"}
        provider_token = (os.getenv("TTS_API_TOKEN") or "").strip()
        if provider_token:
            headers["Authorization"] = f"Bearer {provider_token}"
        try:
            provider_response = requests.post(
                provider_url,
                headers=headers,
                json={"text": text, "voice_id": voice_id, "speed_ratio": payload.get("speed_ratio")},
                timeout=(15, 180),
            )
            provider_response.raise_for_status()
            provider_payload = provider_response.json()
            data = provider_payload.get("data") if isinstance(provider_payload, dict) else None
            audio_url = (
                provider_payload.get("audio_url")
                or provider_payload.get("url")
                or (data.get("link") if isinstance(data, dict) else None)
                or (data.get("url") if isinstance(data, dict) else None)
            )
            if not str(audio_url or "").startswith(("http://", "https://")):
                raise ValueError("TTS 服务未返回音频地址")
            duration = float((data or {}).get("duration") or provider_payload.get("duration") or 0)
            record_resource_event("voice", voice_id, "synthesis", user_id=user["id"])
            return {"audio": {"url": audio_url, "duration": duration, "message": "ok"}}
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail={"code": "tts_provider_failed", "message": f"配音服务调用失败：{exc}"}) from exc

    configured_base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    public_base = configured_base if configured_base and "your-domain.example.com" not in configured_base else f"{request.url.scheme}://{request.url.netloc}"
    try:
        result = synthesize_speech(
            text,
            public_base,
            voice_id=voice_id,
            speed_ratio=payload.get("speed_ratio"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "tts_failed", "message": str(exc)}) from exc
    record_resource_event("voice", voice_id, "synthesis", user_id=user["id"])
    return {"audio": {"url": result["data"]["link"], "duration": result["data"]["duration"], "message": result.get("msg", "ok")}}


@app.get("/api/v1/categories")
def api_categories():
    categories = category_summary()
    return {"categories": categories, "total": sum(item["count"] for item in categories)}


@app.get("/api/v1/workflows")
def api_workflows(
    category: str = Query(default="全部"),
    q: str = Query(default=""),
    sort: str = Query(default="newest"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
):
    items = _workflow_stats(list_workflows(category))
    query = q.strip().lower()
    if query:
        items = [
            item
            for item in items
            if query in " ".join([item["code"], item["name"], item["description"], *item["tags"]]).lower()
        ]
    if sort == "name":
        items.sort(key=lambda item: item["name"])
    elif sort == "favorites":
        items.sort(key=lambda item: item["stats"].get("favorites", 0), reverse=True)
    elif sort == "downloads":
        items.sort(key=lambda item: item["stats"].get("downloads", 0), reverse=True)
    elif sort == "views":
        items.sort(key=lambda item: item["stats"].get("views", 0), reverse=True)
    else:
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    return {"items": items[start : start + page_size], "total": total, "page": page, "page_size": page_size}


@app.get("/api/v1/workflows/{code}")
def api_workflow_detail(code: str, request: Request, category: Optional[str] = Query(default=None)):
    workflow = get_workflow(code, category)
    if not workflow:
        raise HTTPException(status_code=404, detail={"code": "workflow_not_found", "message": "工作流不存在"})
    user = _request_user(request)
    record_resource_event(
        "workflow",
        workflow["code"],
        "view",
        user_id=user["id"] if user else None,
        dedupe_key=_request_event_key(request, workflow["code"], "view"),
    )
    return {"workflow": _workflow_stats([workflow])[0]}


@app.get("/api/v1/workflows/{code}/preview")
def api_workflow_preview(code: str, category: str = Query(default="电商")):
    asset = find_preview_asset(category, code)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "preview_not_found", "message": "暂无预览"})
    path, mime = asset
    return FileResponse(path, media_type=mime)


@app.get("/api/v1/workflows/{code}/downloads")
def api_workflow_downloads(code: str, request: Request, category: str = Query(default="起号")):
    _require_user(request)
    downloads = find_workflow_downloads(category, code)
    if not downloads:
        raise HTTPException(status_code=404, detail={"code": "downloads_not_found", "message": "暂无可下载文件"})
    return {
        "files": [
            {
                "kind": item["kind"],
                "label": item["label"],
                "filename": item["filename"],
                "size": item["size"],
                "url": f"/api/v1/workflows/{str(code).upper()}/download/{item['kind']}?category={category}",
            }
            for item in downloads
        ]
    }


@app.get("/api/v1/workflows/{code}/download/{kind}")
def api_workflow_download(code: str, kind: str, request: Request, category: str = Query(default="起号")):
    if kind not in {"json", "package"}:
        raise HTTPException(status_code=404, detail={"code": "download_not_found", "message": "下载文件不存在"})
    # Prepared JSON files have already had literal credentials and source
    # tokens removed. The original import package remains member-only.
    if kind == "package":
        _require_user(request)
    item = next((entry for entry in find_workflow_downloads(category, code) if entry["kind"] == kind), None)
    if not item:
        raise HTTPException(status_code=404, detail={"code": "download_not_found", "message": "下载文件不存在"})
    user = _request_user(request)
    record_resource_event(
        "workflow",
        str(code).upper(),
        "download",
        user_id=user["id"] if user else None,
        dedupe_key=_request_event_key(request, str(code).upper(), "download"),
    )
    return FileResponse(
        item["path"],
        media_type=item["mime"],
        filename=item["filename"],
    )


@app.post("/api/v1/assets", status_code=201)
async def api_upload_asset(file: UploadFile = File(...)):
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    try:
        asset = create_asset(file.filename or "asset", file.content_type or "", file.file, size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_asset", "message": str(exc)}) from exc
    return {
        "asset": {
            "id": asset["id"],
            "name": asset["original_name"],
            "mime_type": asset["mime_type"],
            "size_bytes": asset["size_bytes"],
            "url": f"/api/v1/assets/{asset['id']}",
        }
    }


@app.get("/api/v1/assets/{asset_id}")
def api_asset_content(asset_id: str):
    asset = get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail={"code": "asset_not_found", "message": "素材不存在"})
    return FileResponse(asset["path"], media_type=asset["mime_type"])


@app.get("/api/generated/{kind}/{filename}")
def api_generated_media(kind: str, filename: str):
    if kind not in {"audio", "image"}:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "generated media not found"})
    path = generated_file_path(kind, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "generated media not found"})
    return FileResponse(path)


@app.get("/api/v1/job-results/{filename}")
def api_job_result(filename: str, request: Request):
    user = _require_user(request)
    if not user_can_access_result(user["id"], filename, allow_all=user.get("role") == "admin"):
        raise HTTPException(status_code=404, detail={"code": "result_not_found", "message": "结果文件不存在"})
    path = get_result_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail={"code": "result_not_found", "message": "结果文件不存在"})
    if path.suffix.lower() == ".mp4":
        return FileResponse(path, media_type="video/mp4")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/v1/jobs/{job_id}/preview-stream")
def api_job_preview_stream(job_id: str, request: Request):
    """Serve the 720p preview as one sequential stream instead of slow R2 ranges."""
    user = _require_user(request)
    job = get_job(job_id)
    if not job or (job.get("user_id") != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "视频任务不存在"})
    result = next((item for item in job.get("results") or [] if item.get("type") == "video"), None)
    source = str((result or {}).get("url") or "").strip()
    if not source:
        raise HTTPException(status_code=404, detail={"code": "preview_not_available", "message": "预览视频不存在"})
    if source.startswith("/api/v1/job-results/"):
        path = get_result_path(Path(source.rsplit("/", 1)[-1]).name)
        if not path:
            raise HTTPException(status_code=404, detail={"code": "preview_not_available", "message": "预览视频不存在"})
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=300"})
    cache_dir = RESULT_DIR / "preview-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = (cache_dir / f"{job_id}.mp4").resolve()
    if not cache_path.is_file():
        temporary = cache_path.with_name(f".{cache_path.name}.{time.time_ns()}.part")
        try:
            upstream = requests.get(source, stream=True, timeout=(20, 300), headers={"Accept": "video/mp4"})
            if upstream.status_code not in {200, 206}:
                status = upstream.status_code
                upstream.close()
                raise HTTPException(status_code=502, detail={"code": "preview_upstream_error", "message": f"预览视频返回 HTTP {status}"})
            total = 0
            with temporary.open("wb") as stream:
                for chunk in upstream.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > int(os.getenv("DEVICE_RENDER_MAX_UPLOAD_BYTES") or 2 * 1024 * 1024 * 1024):
                        raise HTTPException(status_code=413, detail={"code": "preview_too_large", "message": "预览视频超过缓存限制"})
                    stream.write(chunk)
            upstream.close()
            if total < 12:
                raise HTTPException(status_code=502, detail={"code": "preview_empty", "message": "预览视频为空"})
            os.replace(temporary, cache_path)
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail={"code": "preview_upstream_unavailable", "message": "预览视频暂时无法连接"}) from exc
        finally:
            temporary.unlink(missing_ok=True)
    # FileResponse supports HTTP Range itself, so the browser's initial
    # metadata request remains compatible after the one-time local cache fill.
    return FileResponse(cache_path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/v1/downloads/draft-bridge")
def api_download_draft_bridge():
    executable = ROOT / "dist" / HELPER_BINARY_NAME
    if not executable.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "bridge_not_built", "message": f"{HELPER_PRODUCT_NAME}尚未打包"},
        )
    return FileResponse(
        executable,
        media_type="application/vnd.microsoft.portable-executable",
        filename=HELPER_DOWNLOAD_NAME,
        headers={
            "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Helper-Version": HELPER_VERSION,
            "X-Content-SHA256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        },
    )


@app.get("/api/v1/downloads/jianying-compatible")
def api_download_compatible_jianying():
    return RedirectResponse(
        JIANYING_COMPAT_DOWNLOAD_URL,
        status_code=307,
        headers={
            "Cache-Control": "no-store",
            "X-Jianying-Version": JIANYING_COMPAT_VERSION,
            "X-Content-SHA256": JIANYING_COMPAT_SHA256,
        },
    )


@app.post("/api/v1/render-devices/pairing-codes", status_code=201)
def api_create_render_device_pairing_code(request: Request):
    user = _require_ready_user(request)
    return create_pairing_code(user["id"])


@app.get("/api/v1/render-devices")
def api_render_devices(request: Request):
    user = _require_user(request)
    devices = list_devices(user["id"])
    return {"items": devices, "online": any(device["online"] for device in devices)}


@app.delete("/api/v1/render-devices/{device_id}", status_code=204)
def api_revoke_render_device(device_id: str, request: Request):
    user = _require_user(request)
    if not revoke_device(user["id"], device_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "device_not_found", "message": "本机剪映助手不存在"},
        )
    return Response(status_code=204)


@app.post("/api/v1/render-agent/pair")
def api_pair_render_agent(payload: dict = Body(default_factory=dict)):
    try:
        return pair_device(
            str(payload.get("code") or ""),
            str(payload.get("name") or ""),
            str(payload.get("platform") or "windows"),
            payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pairing_code", "message": str(exc)},
        ) from exc


@app.post("/api/v1/render-agent/heartbeat")
def api_render_agent_heartbeat(request: Request, payload: dict = Body(default_factory=dict)):
    device = _require_render_device(request)
    updated = heartbeat_device(
        device["id"],
        payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else None,
    )
    if not updated:
        raise HTTPException(status_code=401, detail={"code": "device_revoked", "message": "设备授权已失效"})
    return {"device": updated}


@app.post("/api/v1/render-agent/claim")
def api_render_agent_claim(request: Request):
    device = _require_render_device(request)
    heartbeat_device(device["id"])
    reported_helper_version = str(
        (device.get("capabilities") or {}).get("helper_version") or ""
    ).strip()
    if reported_helper_version and not _helper_version_at_least(
        reported_helper_version, MINIMUM_RENDER_HELPER_VERSION
    ):
        raise HTTPException(
            status_code=426,
            detail={
                "code": "helper_update_required",
                "message": f"导出助手需要更新到 v{HELPER_VERSION} 后再领取任务",
                "latest_helper_version": HELPER_VERSION,
                "download_url": "/api/v1/downloads/draft-bridge",
            },
        )
    task = claim_device_render_job(
        device["id"],
        int(os.getenv("DEVICE_RENDER_LEASE_SECONDS") or 900),
    )
    if not task:
        return Response(status_code=204)
    return {"task": task}


def _publish_device_video_in_background(job_id: str, result_name: str, destination: Path) -> None:
    try:
        (
            result_url,
            download_url,
            original_bytes,
            published_bytes,
            delivery_mode,
            preview_1080_url,
            preview_1080_bytes,
        ) = publish_device_video(job_id, destination)
    except (OSError, VideoDeliveryError) as exc:
        logger.warning("r2_video_delivery_failed job_id=%s error=%s", job_id, exc)
        append_job_log(job_id, f"R2 视频处理失败，已自动保留站点原片：{exc}", level="warning")
        return

    if not promote_device_render_result(
        job_id,
        result_name,
        result_url,
        download_url,
        preview_1080_url,
    ):
        logger.warning("r2_video_result_not_promoted job_id=%s url=%s", job_id, result_url)
        append_job_log(job_id, "R2 视频已经上传，但任务结果已变化，站点原片予以保留", level="warning")
        return

    job = get_job(job_id)
    if job and job.get("user_id"):
        storage_bytes = original_bytes + (published_bytes if result_url != download_url else 0)
        record_video_storage(
            job_id,
            job["user_id"],
            result_url,
            download_url,
            storage_bytes,
        )

    if delivery_mode == "original_fallback":
        append_job_log(job_id, "网页预览版生成失败，已自动使用 R2 高清原片")
    else:
        saved_percent = max(0, round((1 - (published_bytes / max(1, original_bytes))) * 100))
        append_job_log(
            job_id,
            f"网页流畅预览版与高清下载版已上传到 R2（预览版减少 {saved_percent}%）",
        )
    destination.unlink(missing_ok=True)


def _device_upload_directory(job_id: str, upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", str(upload_id or "")):
        raise HTTPException(status_code=404, detail={"code": "upload_not_found", "message": "上传任务不存在"})
    root = (RESULT_DIR / ".device-uploads").resolve()
    candidate = (root / str(job_id) / upload_id).resolve()
    if root not in candidate.parents:
        raise HTTPException(status_code=404, detail={"code": "upload_not_found", "message": "上传任务不存在"})
    return candidate


def _finish_received_device_video(
    job: dict,
    device: dict,
    result_name: str,
    destination: Path,
    total: int,
    background_tasks: BackgroundTasks,
) -> dict:
    job_id = job["id"]
    if not complete_device_render_job(job_id, device["id"], result_name):
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail={"code": "job_not_rendering", "message": "任务状态已变化"})
    record_video_storage(
        job_id,
        job["user_id"],
        f"/api/v1/job-results/{result_name}",
        f"/api/v1/job-results/{result_name}",
        total,
    )
    if r2_export_configured():
        append_job_log(job_id, "视频已回传，正在后台压缩并上传到 R2")
        background_tasks.add_task(
            _publish_device_video_in_background,
            job_id,
            result_name,
            destination,
        )
    heartbeat_device(device["id"])
    return {"job": _public_job(get_job(job_id))}


def _direct_device_upload_details(job_id: str, device_id: str, size_bytes: int) -> dict:
    upload_base = (os.getenv("R2_EXPORT_UPLOAD_URL") or "").strip().rstrip("/")
    public_base = (os.getenv("R2_EXPORT_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    secret = (os.getenv("R2_EXPORT_UPLOAD_TOKEN") or "").strip()
    if not upload_base or not public_base or not secret:
        raise HTTPException(
            status_code=503,
            detail={"code": "direct_upload_unavailable", "message": "R2 direct upload is not configured"},
        )
    object_name = f"{job_id}-device-original-direct.mp4"
    object_key = f"exports/{object_name}"
    ttl_seconds = int(os.getenv("R2_DEVICE_UPLOAD_TOKEN_TTL_SECONDS") or 7200)
    part_bytes = max(
        5 * 1024 * 1024,
        min(64 * 1024 * 1024, int(os.getenv("R2_DEVICE_UPLOAD_PART_BYTES") or 8 * 1024 * 1024)),
    )
    return {
        "upload_url": f"{upload_base}/{object_name}",
        "public_url": f"{public_base}/{object_name}?stream=full",
        "object_key": object_key,
        "token": create_direct_upload_token(
            secret,
            object_key=object_key,
            job_id=job_id,
            device_id=device_id,
            size_bytes=size_bytes,
            part_bytes=part_bytes,
            ttl_seconds=ttl_seconds,
        ),
        "part_bytes": part_bytes,
        "parallel_uploads": max(1, min(6, int(os.getenv("R2_DEVICE_UPLOAD_PARALLEL_UPLOADS") or 4))),
    }


@app.post("/api/v1/render-agent/jobs/{job_id}/direct-upload")
def api_create_direct_render_agent_upload(
    job_id: str,
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    device = _require_render_device(request)
    job = get_job(job_id)
    if not job or job.get("render_device_id") != device["id"] or job.get("status") != "rendering":
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Export job not found"})
    try:
        size_bytes = int(payload.get("size_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_upload", "message": "Invalid upload size"}) from exc
    max_bytes = min(
        int(os.getenv("DEVICE_RENDER_MAX_UPLOAD_BYTES") or 2 * 1024 * 1024 * 1024),
        int(os.getenv("R2_DEVICE_DIRECT_MAX_UPLOAD_BYTES") or 512 * 1024 * 1024),
    )
    if size_bytes < 12 or size_bytes > max_bytes:
        raise HTTPException(status_code=422, detail={"code": "invalid_upload", "message": "Invalid upload size"})
    heartbeat_device(device["id"])
    return _direct_device_upload_details(job_id, device["id"], size_bytes)


@app.post("/api/v1/render-agent/jobs/{job_id}/direct-upload/complete")
def api_complete_direct_render_agent_upload(
    job_id: str,
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    device = _require_render_device(request)
    job = get_job(job_id)
    owned_by_device = bool(job and job.get("render_device_id") == device["id"])
    if owned_by_device and job.get("status") == "succeeded":
        return {"job": _public_job(job)}
    if not owned_by_device or job.get("status") != "rendering":
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Export job not found"})
    try:
        size_bytes = int(payload.get("size_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_upload", "message": "Invalid upload size"}) from exc
    details = _direct_device_upload_details(job_id, device["id"], size_bytes)
    public_url = str(payload.get("public_url") or "").strip()
    if public_url != details["public_url"]:
        raise HTTPException(status_code=422, detail={"code": "invalid_upload_url", "message": "Unexpected upload URL"})
    try:
        verified = requests.head(public_url, timeout=(10, 30))
        hosted_size = int(verified.headers.get("content-length") or 0)
    except (requests.RequestException, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail={"code": "upload_verification_failed", "message": "R2 upload could not be verified"}) from exc
    if verified.status_code != 200 or hosted_size != size_bytes or size_bytes < 12:
        raise HTTPException(status_code=422, detail={"code": "upload_verification_failed", "message": "R2 object size does not match"})
    if not complete_device_render_job(job_id, device["id"], result_url=public_url):
        raise HTTPException(status_code=409, detail={"code": "job_not_rendering", "message": "Job state changed"})
    record_video_storage(job_id, job["user_id"], public_url, public_url, size_bytes)
    append_job_log(job_id, "Video uploaded directly to R2 by the export helper")
    heartbeat_device(device["id"])
    return {"job": _public_job(get_job(job_id))}


@app.post("/api/v1/render-agent/jobs/{job_id}/uploads", status_code=201)
def api_create_render_agent_upload(job_id: str, request: Request, payload: dict = Body(default_factory=dict)):
    device = _require_render_device(request)
    job = get_job(job_id)
    if not job or job.get("render_device_id") != device["id"] or job.get("status") != "rendering":
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "导出任务不存在"})
    try:
        size_bytes = int(payload.get("size_bytes") or 0)
        total_parts = int(payload.get("total_parts") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_upload", "message": "上传参数无效"}) from exc
    max_bytes = int(os.getenv("DEVICE_RENDER_MAX_UPLOAD_BYTES") or 2 * 1024 * 1024 * 1024)
    if size_bytes < 12 or size_bytes > max_bytes or total_parts < 1 or total_parts > 512:
        raise HTTPException(status_code=422, detail={"code": "invalid_upload", "message": "上传文件大小或分片数量无效"})
    upload_id = uuid.uuid4().hex
    directory = _device_upload_directory(job_id, upload_id)
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "job_id": job_id,
        "device_id": device["id"],
        "size_bytes": size_bytes,
        "total_parts": total_parts,
        "created_at": time.time(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    heartbeat_device(device["id"])
    return {"upload_id": upload_id}


def _load_device_upload(job_id: str, upload_id: str, device_id: str) -> tuple[Path, dict]:
    directory = _device_upload_directory(job_id, upload_id)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail={"code": "upload_not_found", "message": "上传任务不存在"}) from exc
    if manifest.get("job_id") != job_id or manifest.get("device_id") != device_id:
        raise HTTPException(status_code=404, detail={"code": "upload_not_found", "message": "上传任务不存在"})
    return directory, manifest


@app.put("/api/v1/render-agent/jobs/{job_id}/uploads/{upload_id}/{part_number}")
async def api_upload_render_agent_part(
    job_id: str,
    upload_id: str,
    part_number: int,
    request: Request,
    chunk: UploadFile = File(...),
):
    device = _require_render_device(request)
    job = get_job(job_id)
    if not job or job.get("render_device_id") != device["id"] or job.get("status") != "rendering":
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "导出任务不存在"})
    directory, manifest = _load_device_upload(job_id, upload_id, device["id"])
    if part_number < 1 or part_number > int(manifest["total_parts"]):
        raise HTTPException(status_code=422, detail={"code": "invalid_part", "message": "视频分片编号无效"})
    destination = directory / f"{part_number:04d}.part"
    temporary = directory / f".{part_number:04d}.{time.time_ns()}.part"
    total = 0
    try:
        with temporary.open("wb") as stream:
            while block := await chunk.read(1024 * 1024):
                total += len(block)
                if total > DEVICE_UPLOAD_PART_MAX_BYTES:
                    raise HTTPException(status_code=413, detail={"code": "part_too_large", "message": "视频分片过大"})
                stream.write(block)
        if total <= 0:
            raise HTTPException(status_code=422, detail={"code": "empty_part", "message": "视频分片为空"})
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    heartbeat_device(device["id"])
    return {"part_number": part_number, "size_bytes": total}


@app.post("/api/v1/render-agent/jobs/{job_id}/uploads/{upload_id}/complete")
def api_complete_chunked_render_agent_upload(
    job_id: str,
    upload_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    device = _require_render_device(request)
    job = get_job(job_id)
    owned_by_device = bool(job and job.get("render_device_id") == device["id"])
    if owned_by_device and job.get("status") == "succeeded":
        return {"job": _public_job(job)}
    if not owned_by_device or job.get("status") != "rendering":
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "导出任务不存在"})
    directory, manifest = _load_device_upload(job_id, upload_id, device["id"])
    parts = [directory / f"{number:04d}.part" for number in range(1, int(manifest["total_parts"]) + 1)]
    if any(not part.is_file() for part in parts):
        raise HTTPException(status_code=409, detail={"code": "parts_missing", "message": "视频分片尚未全部上传"})
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_name = f"{job_id}-device.mp4"
    destination = (RESULT_DIR / result_name).resolve()
    temporary = (RESULT_DIR / f".{result_name}.{time.time_ns()}.part").resolve()
    total = 0
    first_chunk = b""
    try:
        with temporary.open("wb") as stream:
            for part in parts:
                with part.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        if not first_chunk:
                            first_chunk = block[:64]
                        total += len(block)
                        stream.write(block)
        if total != int(manifest["size_bytes"]) or b"ftyp" not in first_chunk:
            raise HTTPException(status_code=422, detail={"code": "invalid_video", "message": "合并后的视频文件无效"})
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    shutil.rmtree(directory, ignore_errors=True)
    return _finish_received_device_video(job, device, result_name, destination, total, background_tasks)


@app.post("/api/v1/render-agent/jobs/{job_id}/complete")
async def api_complete_render_agent_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
):
    device = _require_render_device(request)
    job = get_job(job_id)
    owned_by_device = bool(
        job
        and job.get("render_device_id") == device["id"]
    )
    if owned_by_device and job.get("status") == "succeeded":
        heartbeat_device(device["id"])
        return {"job": _public_job(job)}
    if (
        not owned_by_device
        or job.get("status") != "rendering"
    ):
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "导出任务不存在"})

    max_bytes = int(os.getenv("DEVICE_RENDER_MAX_UPLOAD_BYTES") or 2 * 1024 * 1024 * 1024)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_name = f"{job_id}-device.mp4"
    destination = (RESULT_DIR / result_name).resolve()
    temporary = (RESULT_DIR / f".{result_name}.{time.time_ns()}.part").resolve()
    total = 0
    first_chunk = b""
    try:
        with temporary.open("wb") as stream:
            while chunk := await video.read(1024 * 1024):
                if not first_chunk:
                    first_chunk = chunk[:64]
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail={"code": "video_too_large", "message": "导出视频超过上传大小限制"},
                    )
                stream.write(chunk)
        if total < 12 or b"ftyp" not in first_chunk:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_video", "message": "上传结果不是有效的 MP4 文件"},
            )
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    return _finish_received_device_video(job, device, result_name, destination, total, background_tasks)


@app.post("/api/v1/render-agent/jobs/{job_id}/progress")
def api_render_agent_job_progress(job_id: str, request: Request, payload: dict = Body(default_factory=dict)):
    device = _require_render_device(request)
    try:
        progress = int(payload.get("progress") or 82)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_progress", "message": "本机导出进度格式不正确"},
        )
    if not report_device_render_progress(
        job_id,
        device["id"],
        stage=str(payload.get("stage") or ""),
        progress=progress,
        message=str(payload.get("message") or "")[:500],
    ):
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "导出任务不存在"})
    heartbeat_device(device["id"])
    return {"job": _public_job(get_job(job_id))}


@app.post("/api/v1/render-agent/jobs/{job_id}/fail")
def api_fail_render_agent_job(job_id: str, request: Request, payload: dict = Body(default_factory=dict)):
    device = _require_render_device(request)
    if not fail_device_render_job(
        job_id,
        device["id"],
        str(payload.get("code") or "device_render_failed"),
        str(payload.get("message") or "本机剪映导出失败"),
    ):
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "导出任务不存在"})
    heartbeat_device(device["id"])
    return {"job": _public_job(get_job(job_id))}


@app.post("/api/v1/jobs", status_code=202)
def api_create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: dict = Body(default_factory=dict),
):
    user = _require_ready_user(request)
    workflow_code = str(payload.get("workflow_code") or "").upper()
    category = str(payload.get("category") or "").strip()
    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_inputs", "message": "inputs 必须是对象"})
    workflow = get_workflow(workflow_code, category)
    needs_render = bool(workflow and workflow.get("output_type") == "draft")
    render_device, _ = _preferred_render_device(user) if needs_render else (None, False)
    if (
        needs_render
        and not render_device
        and not (os.getenv("WORKFLOW_RENDER_API_URL") or "").strip()
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "render_device_required",
                "message": "请先配对并启动本机剪映导出助手，再运行这个工作流",
            },
        )
    job_id = uuid.uuid4().hex
    pricing = _reserve_job_quota(user, job_id, workflow_code)
    try:
        job = create_job(
            workflow_code,
            category,
            inputs,
            user["id"],
            render_device["id"] if render_device else None,
            job_id,
            pricing["provider_cost_points"],
            pricing["price_points"],
        )
    except KeyError as exc:
        settle_generation_reservation(job_id, False)
        raise HTTPException(status_code=404, detail={"code": "workflow_not_found", "message": "工作流不存在"}) from exc
    except PermissionError as exc:
        settle_generation_reservation(job_id, False)
        raise HTTPException(status_code=409, detail={"code": "workflow_not_online", "message": "工作流正在接入中"}) from exc
    except ValueError as exc:
        settle_generation_reservation(job_id, False)
        raise HTTPException(status_code=422, detail={"code": "invalid_inputs", "message": str(exc)}) from exc
    except Exception:
        settle_generation_reservation(job_id, False)
        raise
    enqueue_job(job["id"], background_tasks)
    return {"job": _public_job(job)}


@app.post("/api/v1/draft-key-renders", status_code=202)
def api_create_draft_key_render(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: dict = Body(default_factory=dict),
):
    """Queue a Jianying-native MP4 export without exposing the Windows worker."""
    user = _require_ready_user(request)
    render_device, _ = _preferred_render_device(user)
    job_id = uuid.uuid4().hex
    pricing = _reserve_job_quota(user, job_id, DRAFT_KEY_RENDER_CODE)
    try:
        job = create_draft_key_render_job(
            payload.get("draft_key") or payload.get("key") or payload,
            user["id"],
            render_device["id"] if render_device else None,
            job_id,
            pricing["provider_cost_points"],
            pricing["price_points"],
        )
    except PermissionError as exc:
        settle_generation_reservation(job_id, False)
        raise HTTPException(
            status_code=409,
            detail={"code": "render_device_required", "message": "请先配对并启动本机剪映导出助手"},
        ) from exc
    except ValueError as exc:
        settle_generation_reservation(job_id, False)
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_draft_key", "message": str(exc)},
        ) from exc
    except Exception:
        settle_generation_reservation(job_id, False)
        raise
    enqueue_job(job["id"], background_tasks)
    return {"job": _public_job(job)}


@app.get("/api/v1/draft-key-renders/status")
def api_draft_key_render_status(request: Request):
    user = _request_user(request)
    devices = list_devices(user["id"]) if user else []
    render_device, shared_device = _preferred_render_device(user) if user else (None, False)
    device_online = bool(render_device)
    central_configured = bool((os.getenv("WORKFLOW_RENDER_API_URL") or "").strip())
    configured = device_online or central_configured
    return {
        "configured": configured,
        "device_online": device_online,
        "central_configured": central_configured,
        "shared_device": shared_device,
        "latest_helper_version": HELPER_VERSION,
        "devices": devices,
        "message": "管理员共享剪映导出助手在线" if shared_device else "本机剪映导出助手在线" if device_online else (
            "剪映原生导出服务可用" if central_configured else "请先配对并启动本机剪映导出助手"
        ),
    }


@app.get("/api/v1/jobs")
def api_jobs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str = Query(default=""),
    workflow_code: str = Query(default=""),
):
    user = _require_user(request)
    try:
        jobs, total = list_jobs(
            user["id"],
            page,
            page_size,
            status=status,
            workflow_code=workflow_code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": "不支持的任务筛选条件"},
        ) from exc
    return {
        "items": [_public_job(job) for job in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/v1/jobs/{job_id}")
def api_job(job_id: str, request: Request):
    user = _require_user(request)
    job = get_job(job_id)
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在"})
    return {"job": _public_job(job)}


@app.get("/api/v1/jobs/{job_id}/logs")
def api_job_logs(job_id: str, request: Request, after_id: int = Query(default=0, ge=0)):
    user = _require_user(request)
    job = get_job(job_id)
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在"})
    return {"items": get_job_logs(job_id, after_id=after_id)}


@app.post("/api/v1/vod/renders", status_code=202)
def api_create_vod_render(payload: dict = Body(default_factory=dict)):
    """Upload a draft_key's assets and submit a server-side VOD edit task."""
    key = payload.get("key") or payload.get("draft_key")
    if not isinstance(key, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_draft_key", "message": "key must be a JSON object"},
        )
    dry_run = bool(payload.get("dry_run", False))
    try:
        result = render_draft_key_vod(
            key,
            base_dir=ROOT,
            submit=not dry_run,
            wait=bool(payload.get("wait", False)),
            include_text=bool(payload.get("include_text", True)),
            include_effects=bool(payload.get("include_effects", True)),
        )
    except KeyValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_draft_key", "message": str(exc), "errors": exc.errors},
        ) from exc
    except VodConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "vod_not_configured", "message": str(exc)},
        ) from exc
    except VodRenderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "vod_render_error", "message": str(exc)},
        ) from exc

    response = {
        "success": result["success"],
        "submitted": result["submitted"],
        "req_id": result.get("req_id"),
        "space": result["space"],
        "conversion": result["conversion"],
    }
    if dry_run:
        response["edit_param"] = result["edit_param"]
    if result.get("result"):
        response["result"] = result["result"]
    return response


@app.get("/api/v1/account/quota")
def api_account_quota(request: Request):
    user = _require_user(request)
    return {"quota": quota_snapshot(user["id"])}


@app.get("/api/v1/admin/user-quotas")
def api_admin_user_quotas(request: Request):
    _require_admin(request)
    items = list_user_quotas()
    return {"items": items, "total": len(items)}


@app.get("/api/v1/admin/provider-usage")
def api_admin_provider_usage(request: Request, days: int = Query(default=30, ge=1, le=365)):
    _require_admin(request)
    return {"usage": provider_usage_snapshot(days)}


@app.get("/api/v1/admin/health-check")
def api_admin_health_check(request: Request):
    _require_admin(request)
    return {"health": latest_health_check()}


@app.post("/api/v1/admin/health-check")
def api_run_admin_health_check(request: Request):
    _require_admin(request)
    return {"health": run_health_check("admin_manual")}


@app.get("/api/v1/admin/jobs")
def api_admin_jobs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str = Query(default=""),
    workflow_code: str = Query(default=""),
    user_id: str = Query(default=""),
    q: str = Query(default="", max_length=100),
):
    _require_admin(request)
    quota_items = list_user_quotas()
    users = {item["user"]["id"]: item["user"] for item in quota_items}
    normalized_query = str(q or "").strip().lower()
    query_user_ids = [
        user["id"]
        for user in users.values()
        if normalized_query and normalized_query in f"{user.get('email') or ''} {user.get('username') or ''}".lower()
    ]
    try:
        jobs, total, summary = list_admin_jobs(
            page,
            page_size,
            status=status,
            workflow_code=workflow_code,
            user_id=user_id,
            query=normalized_query,
            query_user_ids=query_user_ids,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": "不支持的任务筛选条件"},
        ) from exc
    fallback = {"username": "已删除用户", "email": None, "role": "user", "active": False}
    return {
        "items": [
            {**_public_job(job), "user": {"id": job.get("user_id") or "", **users.get(job.get("user_id"), fallback)}}
            for job in jobs
        ],
        "users": list(users.values()),
        "summary": summary,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.delete("/api/v1/admin/jobs/queue")
def api_clear_admin_job_queue(request: Request):
    _require_admin(request)
    result = clear_active_jobs()
    return {
        **result,
        "message": f"已清空 {result['cleared']} 个活动任务，退回 {result['refunded']} 笔冻结积分",
    }


def _admin_password_reauthentication(admin: dict, password: str) -> None:
    if not password or not verify_user_password(admin["id"], password):
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_password_invalid", "message": "管理员密码不正确"},
        )


def _request_source_ip(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


@app.post("/api/v1/admin/users/{user_id}/password/reveal")
def api_admin_reveal_user_password(
    user_id: str,
    request: Request,
    response: Response,
    payload: dict = Body(default_factory=dict),
):
    admin = _require_admin(request)
    _admin_password_reauthentication(admin, str(payload.get("admin_password") or ""))
    try:
        password = reveal_user_password(admin["id"], user_id, _request_source_ip(request))
    except KeyError as exc:
        code = str(exc.args[0]) if exc.args else "password_not_recoverable"
        status = 404 if code == "user_not_found" else 409
        message = "用户不存在" if code == "user_not_found" else "该账号尚无可恢复密码，请先重置一次"
        raise HTTPException(status_code=status, detail={"code": code, "message": message}) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": str(exc), "message": "管理员密码不允许通过此入口查看"},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": str(exc), "message": "密码保险库暂不可用"},
        ) from exc
    response.headers["Cache-Control"] = "no-store, private"
    return {"user_id": user_id, "password": password}


@app.post("/api/v1/admin/users/{user_id}/password/reset")
def api_admin_reset_user_password(
    user_id: str,
    request: Request,
    response: Response,
    payload: dict = Body(default_factory=dict),
):
    admin = _require_admin(request)
    _admin_password_reauthentication(admin, str(payload.get("admin_password") or ""))
    try:
        password = reset_user_password_for_admin(
            admin["id"],
            user_id,
            str(payload.get("new_password") or ""),
            _request_source_ip(request),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "user_not_found", "message": "用户不存在"},
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": str(exc), "message": "管理员密码不允许通过此入口重置"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc), "message": "新密码长度必须为 8 至 128 个字符"},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": str(exc), "message": "密码保险库暂不可用"},
        ) from exc
    response.headers["Cache-Control"] = "no-store, private"
    return {"user_id": user_id, "password": password, "message": "密码已重置并写入保险库"}


@app.put("/api/v1/admin/user-quotas/{user_id}")
def api_adjust_user_quota(
    user_id: str,
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    _require_admin(request)
    try:
        generation_delta = int(payload.get("points_delta", payload.get("generation_delta")) or 0)
        storage_limit_gb = payload.get("storage_limit_gb")
        storage_limit_bytes = None if storage_limit_gb in (None, "") else round(float(storage_limit_gb) * 1024 * 1024 * 1024)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_quota_adjustment", "message": "额度调整数值格式不正确"},
        ) from exc
    if not -10_000 <= generation_delta <= 10_000:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_generation_delta", "message": "单次积分调整范围为 -10000 到 10000"},
        )
    if storage_limit_bytes is not None and not 0 <= storage_limit_bytes <= 10 * 1024**4:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_storage_limit", "message": "云存储上限必须在 0 到 10240GB 之间"},
        )
    try:
        quota = adjust_user_quota(
            user_id,
            generation_delta=generation_delta,
            storage_limit_bytes=storage_limit_bytes,
            detail=str(payload.get("detail") or "管理员调整积分"),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "user_not_found", "message": "账号不存在"},
        ) from exc
    return {"quota": quota, "message": "用户积分与存储额度已更新"}


@app.get("/api/v1/admin/workflow-pricing")
def api_admin_workflow_pricing(request: Request):
    _require_admin(request)
    items = []
    for workflow in list_workflows("全部"):
        items.append(
            {
                "workflow": {
                    "code": workflow["code"],
                    "name": workflow["name"],
                    "status": workflow["status"],
                    "categories": workflow.get("categories") or [],
                },
                "pricing": workflow_pricing_snapshot(workflow["code"]),
            }
        )
    items.sort(key=lambda item: (item["workflow"]["status"] != "online", item["workflow"]["code"]))
    return {"items": items, "total": len(items)}


@app.put("/api/v1/admin/workflow-pricing/{workflow_code}")
def api_update_workflow_pricing(
    workflow_code: str,
    request: Request,
    payload: dict = Body(default_factory=dict),
):
    _require_admin(request)
    workflow = get_workflow(workflow_code)
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail={"code": "workflow_not_found", "message": "工作流不存在"},
        )
    try:
        pricing = update_workflow_pricing(
            workflow_code,
            coze_cost_points=int(payload.get("coze_cost_points") or 0),
            mihe_cost_points=int(payload.get("mihe_cost_points") or 0),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_workflow_pricing", "message": "供应商成本积分必须是 0 到 1000000 的整数"},
        ) from exc
    return {"pricing": pricing, "message": "工作流积分价格已更新"}


@app.get("/api/v1/vod/renders/{req_id}")
def api_vod_render_status(req_id: str):
    """Return cloud render progress and output media metadata."""
    try:
        renderer = VolcengineVodRenderer()
        progress = renderer.get_progress(req_id)
        result = renderer.get_result(req_id)
        items = result.get("Result") or []
        item = items[0] if isinstance(items, list) and items else {}
        output_vid = str(item.get("OutputVid") or "")
        media = renderer.get_media_info(output_vid) if output_vid else None
    except VodConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "vod_not_configured", "message": str(exc)},
        ) from exc
    except VodRenderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "vod_render_error", "message": str(exc)},
        ) from exc
    return {
        "req_id": req_id,
        "status": item.get("Status"),
        "progress": progress.get("Result"),
        "message": item.get("Message"),
        "output_vid": output_vid or None,
        "media": media,
    }


@app.post("/api/v1/jobs/{job_id}/retry", status_code=202)
def api_retry_job(job_id: str, request: Request, background_tasks: BackgroundTasks):
    user = _require_ready_user(request)
    old_job = get_job(job_id)
    if not old_job or old_job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在"})
    if old_job["status"] != "failed":
        raise HTTPException(status_code=409, detail={"code": "job_not_failed", "message": "只有失败任务可以重试"})
    render_device, _ = _preferred_render_device(user)
    next_job_id = uuid.uuid4().hex
    pricing = _reserve_job_quota(user, next_job_id, old_job["workflow_code"])
    if old_job["workflow_code"] == DRAFT_KEY_RENDER_CODE:
        try:
            job = create_draft_key_render_job(
                old_job["inputs"],
                old_job.get("user_id"),
                render_device["id"] if render_device else None,
                next_job_id,
                pricing["provider_cost_points"],
                pricing["price_points"],
            )
        except PermissionError as exc:
            settle_generation_reservation(next_job_id, False)
            raise HTTPException(
                status_code=409,
                detail={"code": "render_device_required", "message": "请先启动本机剪映导出助手再重试"},
            ) from exc
        except Exception:
            settle_generation_reservation(next_job_id, False)
            raise
    else:
        workflow = get_workflow(old_job["workflow_code"], old_job["category"])
        if (
            workflow
            and workflow.get("generation_mode") == "draft"
            and not render_device
            and not (os.getenv("WORKFLOW_RENDER_API_URL") or "").strip()
        ):
            settle_generation_reservation(next_job_id, False)
            raise HTTPException(
                status_code=409,
                detail={"code": "render_device_required", "message": "请先启动本机剪映导出助手再重试"},
            )
        try:
            job = create_job(
                old_job["workflow_code"],
                old_job["category"],
                old_job["inputs"],
                old_job.get("user_id"),
                render_device["id"] if render_device and workflow and workflow.get("generation_mode") == "draft" else None,
                next_job_id,
                pricing["provider_cost_points"],
                pricing["price_points"],
            )
        except Exception:
            settle_generation_reservation(next_job_id, False)
            raise
    enqueue_job(job["id"], background_tasks)
    return {"job": _public_job(job)}


def _admin_retry_job_for_user(job_id: str, user: dict, background_tasks: BackgroundTasks) -> dict:
    """Retry a failed job on behalf of its owner; quota is charged to that owner."""
    old_job = get_job(job_id)
    if not old_job or old_job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在"})
    if old_job["status"] != "failed":
        raise HTTPException(status_code=409, detail={"code": "job_not_failed", "message": "只有失败任务可以重试"})
    render_device, _ = _preferred_render_device(user)
    next_job_id = uuid.uuid4().hex
    pricing = _reserve_job_quota(user, next_job_id, old_job["workflow_code"])
    if old_job["workflow_code"] == DRAFT_KEY_RENDER_CODE:
        try:
            job = create_draft_key_render_job(
                old_job["inputs"], old_job.get("user_id"),
                render_device["id"] if render_device else None, next_job_id,
                pricing["provider_cost_points"], pricing["price_points"],
            )
        except PermissionError as exc:
            settle_generation_reservation(next_job_id, False)
            raise HTTPException(status_code=409, detail={"code": "render_device_required", "message": "请先启动剪映导出助手再重试"}) from exc
        except Exception:
            settle_generation_reservation(next_job_id, False)
            raise
    else:
        workflow = get_workflow(old_job["workflow_code"], old_job["category"])
        if workflow and workflow.get("generation_mode") == "draft" and not render_device and not (os.getenv("WORKFLOW_RENDER_API_URL") or "").strip():
            settle_generation_reservation(next_job_id, False)
            raise HTTPException(status_code=409, detail={"code": "render_device_required", "message": "请先启动剪映导出助手再重试"})
        try:
            job = create_job(
                old_job["workflow_code"], old_job["category"], old_job["inputs"], old_job.get("user_id"),
                render_device["id"] if render_device and workflow and workflow.get("generation_mode") == "draft" else None,
                next_job_id, pricing["provider_cost_points"], pricing["price_points"],
            )
        except Exception:
            settle_generation_reservation(next_job_id, False)
            raise
    enqueue_job(job["id"], background_tasks)
    return {"job": _public_job(job)}


@app.post("/api/v1/admin/jobs/{job_id}/retry", status_code=202)
def api_admin_retry_job(job_id: str, request: Request, background_tasks: BackgroundTasks):
    _require_admin(request)
    old_job = get_job(job_id)
    if not old_job or not old_job.get("user_id"):
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在"})
    target = next(
        (item["user"] for item in list_user_quotas() if item["user"]["id"] == old_job["user_id"]),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail={"code": "user_not_found", "message": "任务所属用户不存在"})
    return _admin_retry_job_for_user(job_id, target, background_tasks)


@app.post("/api/v1/jobs/{job_id}/preview-quality")
def api_unlock_job_preview(job_id: str, request: Request, payload: dict = Body(default_factory=dict)):
    """Unlock the fast-start 1080p preview for a completed video."""
    user = _require_user(request)
    job = get_job(job_id)
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Job not found"})
    if job.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail={"code": "video_not_ready", "message": "瑙嗛灏氭湭瀹屾垚"})
    quality = str(payload.get("quality") or "1080").strip()
    if quality != "1080":
        raise HTTPException(status_code=422, detail={"code": "unsupported_preview_quality", "message": "鏆傛椂鍙敮鎸?1080P"})
    result = next((item for item in job.get("results") or [] if item.get("type") == "video"), None)
    # Never use the original master as a browser preview.  It is intentionally
    # kept for downloading only; the background delivery creates this dedicated
    # fast-start 1080p copy after export.
    high_url = str(
        (result or {}).get("preview_1080_url")
        or (result or {}).get("url")
        or (result or {}).get("download_url")
        or ""
    ).strip()
    if not high_url:
        raise HTTPException(status_code=409, detail={"code": "preview_not_available", "message": "1080P preview is not available"})
    try:
        quota, charged = unlock_video_preview(user["id"], job_id, quality)
    except QuotaError as exc:
        code = str(exc)
        message = "积分不足，无法解锁 1080P 预览" if code == "generation_quota_exhausted" else "无法解锁预览"
        raise HTTPException(status_code=409, detail={"code": code, "message": message}) from exc
    return {
        "quality": quality,
        "url": high_url,
        "charged_points": PREVIEW_1080_UNLOCK_POINTS if charged else 0,
        "quota": quota,
        "message": "1080P preview unlocked" if charged else "1080P preview already unlocked",
    }


@app.delete("/api/v1/jobs/{job_id}/video")
def api_delete_job_video(job_id: str, request: Request):
    user = _require_user(request)
    job = get_job(job_id)
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": "任务不存在"},
        )
    video_urls = {
        str(value).strip()
        for result in job.get("results") or []
        if result.get("type") == "video"
        for value in (
            result.get("url"),
            result.get("preview_1080_url"),
            result.get("download_url"),
        )
        if str(value or "").strip()
    }
    if not video_urls:
        raise HTTPException(
            status_code=409,
            detail={"code": "video_not_available", "message": "该记录没有可删除的视频"},
        )
    try:
        for url in video_urls:
            delete_video_from_r2(url)
    except VideoDeliveryError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "video_delete_failed", "message": str(exc)},
        ) from exc
    if not delete_job_video_results(job_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "video_delete_failed", "message": "视频状态已发生变化，请刷新后重试"},
        )
    quota_before_delete = quota_snapshot(user["id"])
    released_bytes = mark_video_storage_deleted(job_id, user["id"])
    quota_after_delete = quota_snapshot(user["id"])
    released_points = max(
        0,
        int(quota_after_delete.get("points_balance", 0))
        - int(quota_before_delete.get("points_balance", 0)),
    )
    return {
        "job": _public_job(get_job(job_id)),
        "quota": quota_after_delete,
        "released_bytes": released_bytes,
        "released_points": released_points,
        "message": "云端视频已删除，存储空间已经释放",
    }


@app.get("/api/v1/demo/G218/result", include_in_schema=False)
def demo_g218_result():
    return FileResponse(ROOT / "background.png", media_type="image/png")


@app.get("/api/v1/demo/G159/result", include_in_schema=False)
def demo_g159_result():
    return FileResponse(ROOT / "static" / "workflow-previews" / "减肥" / "G159-demo.mp4", media_type="video/mp4")


def _public_job(job: dict) -> dict:
    inputs = job.get("inputs") if isinstance(job.get("inputs"), dict) else {}
    display_title = ""
    if job["workflow_code"] == DRAFT_KEY_RENDER_CODE:
        display_title = "剪映草稿导出"
    else:
        for key in (
            "theme",
            "book_name",
            "cigarette_name",
            "god_name",
            "subject",
            "title",
            "name",
        ):
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                display_title = value.strip()[:100]
                break
    if not display_title:
        workflow = get_workflow(job["workflow_code"], job["category"])
        display_title = str((workflow or {}).get("name") or job["workflow_code"])
    public_results = [
        result
        for result in (job["results"] if job["status"] == "succeeded" else [])
        if isinstance(result, dict) and result.get("type") != "draft"
    ]
    return {
        "id": job["id"],
        "workflow_code": job["workflow_code"],
        "category": job["category"],
        "display_title": display_title,
        "status": job["status"],
        "stage": job["stage"],
        "failed_stage": job.get("failed_stage"),
        "progress": job["progress"],
        "price_points": int(job.get("price_cents") or 0),
        "billing": {
            "status": "charged" if job["status"] == "succeeded" else "refunded" if job["status"] == "failed" else "reserved",
            "price_points": int(job.get("price_cents") or 0),
            "charged_points": int(job.get("price_cents") or 0) if job["status"] == "succeeded" else 0,
            "reserved_points": int(job.get("price_cents") or 0) if job["status"] in {"queued", "running", "rendering"} else 0,
            "refunded_points": int(job.get("price_cents") or 0) if job["status"] == "failed" else 0,
        },
        "results": public_results,
        "error": (
            {"code": job["error_code"], "message": job["error_message"]}
            if job.get("error_code")
            else None
        ),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


# ----------------------- compatibility APIs ----------------------------


@app.get("/api/business/categories")
def compatibility_categories():
    return {"categories": category_summary()}


@app.get("/api/business/workflows")
def compatibility_workflows(category: str = Query(default="全部"), sort: str = Query(default="newest")):
    workflows = _workflow_stats(list_workflows(category))
    if sort in {"favorites", "downloads", "views"}:
        workflows.sort(key=lambda item: item["stats"].get(sort, 0), reverse=True)
    elif sort == "name":
        workflows.sort(key=lambda item: item["name"])
    else:
        workflows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"category": category, "total": len(workflows), "workflows": workflows}


@app.get("/api/business/preview/{category}/{code}")
def compatibility_preview(category: str, code: str):
    return api_workflow_preview(code, category)


@app.get("/api/workflow-categories")
def legacy_image_categories():
    result = []
    for item in workflow_categories():
        kind = item["kind"]
        count = len(IMAGE_WORKFLOWS) if kind == "全部" else sum(w["kind"] == kind for w in IMAGE_WORKFLOWS)
        result.append({**item, "count": count})
    return {"categories": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=int(os.getenv("PORT") or 8000), reload=False)
