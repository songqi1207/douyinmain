"""FastAPI entrypoint for the React workflow center and legacy Flask tools."""

from __future__ import annotations

import hashlib
import json
import os
import time
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.wsgi import WSGIMiddleware

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from business_workflows import find_preview_asset, find_workflow_downloads
from site_accounts import (
    SESSION_TTL_SECONDS,
    authenticate_user,
    complete_registration_approval,
    create_session,
    delete_session,
    fail_registration_delivery,
    favorite_ids,
    list_registration_applications,
    prepare_registration_approval,
    record_resource_event,
    reject_registration_application,
    resource_stats,
    site_account_summary,
    submit_registration_application,
    toggle_favorite,
    user_from_session,
)
from workflow_catalog import IMAGE_WORKFLOWS, workflow_categories
from workflow_jobs import create_asset, create_job, enqueue_job, get_asset, get_job, get_result_path, job_summary, list_jobs, workflow_job_counts
from workflow_registry import category_summary, get_workflow, list_workflows
from utils.draft_key_importer import KeyValidationError
from utils.email_delivery import EmailConfigurationError, email_delivery_status, send_registration_approved
from utils.local_media_generation import list_system_voices, synthesize_speech
from utils.volcengine_vod_renderer import (
    VodConfigurationError,
    VodRenderError,
    VolcengineVodRenderer,
    render_draft_key_vod,
)


ROOT = Path(__file__).resolve().parent
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


def _spa_index() -> FileResponse | HTMLResponse:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    fallback = ROOT / "templates" / "business.html"
    return HTMLResponse(fallback.read_text(encoding="utf-8"))


def _request_user(request: Request) -> dict | None:
    return user_from_session(request.cookies.get(SESSION_COOKIE))


def _require_user(request: Request) -> dict:
    user = _request_user(request)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "login_required", "message": "请先登录"})
    return user


def _require_admin(request: Request) -> dict:
    user = _require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "仅管理员可以审核注册申请"})
    return user


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
def root_redirect():
    return RedirectResponse("/business")


@app.get("/business", response_class=HTMLResponse, include_in_schema=False)
def business_spa():
    return _spa_index()


@app.get("/business/{path:path}", response_class=HTMLResponse, include_in_schema=False)
def business_spa_route(path: str):
    return _spa_index()


@app.get("/workflows", response_class=HTMLResponse, include_in_schema=False)
def legacy_workflow_catalog_page():
    return HTMLResponse((ROOT / "templates" / "workflows.html").read_text(encoding="utf-8"))


# ----------------------------- API v1 ---------------------------------


@app.post("/api/v1/auth/register", status_code=202)
def api_register(payload: dict = Body(default_factory=dict)):
    try:
        application = submit_registration_application(str(payload.get("email") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_registration", "message": str(exc)}) from exc
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


@app.post("/api/v1/auth/logout", status_code=204)
def api_logout(request: Request, response: Response):
    delete_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


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
    user = _require_user(request)
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
            f"{public_base}/legacy",
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
def api_workflow_detail(code: str, request: Request, category: str | None = Query(default=None)):
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


@app.get("/api/v1/job-results/{filename}")
def api_job_result(filename: str):
    path = get_result_path(filename)
    if not path:
        raise HTTPException(status_code=404, detail={"code": "result_not_found", "message": "结果文件不存在"})
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.post("/api/v1/jobs", status_code=202)
def api_create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: dict = Body(default_factory=dict),
):
    user = _require_user(request)
    workflow_code = str(payload.get("workflow_code") or "").upper()
    category = str(payload.get("category") or "").strip()
    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_inputs", "message": "inputs 必须是对象"})
    try:
        job = create_job(workflow_code, category, inputs, user["id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "workflow_not_found", "message": "工作流不存在"}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "workflow_not_online", "message": "工作流正在接入中"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_inputs", "message": str(exc)}) from exc
    enqueue_job(job["id"], background_tasks)
    return {"job": _public_job(job)}


@app.get("/api/v1/jobs")
def api_jobs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    user = _require_user(request)
    jobs, total = list_jobs(user["id"], page, page_size)
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
    user = _require_user(request)
    old_job = get_job(job_id)
    if not old_job or old_job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "任务不存在"})
    if old_job["status"] != "failed":
        raise HTTPException(status_code=409, detail={"code": "job_not_failed", "message": "只有失败任务可以重试"})
    job = create_job(old_job["workflow_code"], old_job["category"], old_job["inputs"], old_job.get("user_id"))
    enqueue_job(job["id"], background_tasks)
    return {"job": _public_job(job)}


@app.get("/api/v1/demo/G218/result", include_in_schema=False)
def demo_g218_result():
    return FileResponse(ROOT / "background.png", media_type="image/png")


@app.get("/api/v1/demo/G159/result", include_in_schema=False)
def demo_g159_result():
    return FileResponse(ROOT / "static" / "workflow-previews" / "减肥" / "G159-demo.mp4", media_type="video/mp4")


def _public_job(job: dict) -> dict:
    return {
        "id": job["id"],
        "workflow_code": job["workflow_code"],
        "category": job["category"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "results": job["results"],
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


@app.get("/api/workflows")
def legacy_image_workflows():
    return {"total": len(IMAGE_WORKFLOWS), "workflows": IMAGE_WORKFLOWS}


# Existing Flask tools remain available during migration.
try:
    from app import create_app as create_flask_app

    app.mount("/legacy", WSGIMiddleware(create_flask_app()))
except Exception as exc:  # pragma: no cover - startup remains useful for the React/API surface
    print(f"[legacy] Flask compatibility mount unavailable: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fastapi_app:app", host="0.0.0.0", port=int(os.getenv("PORT") or 8000), reload=False)
