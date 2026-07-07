#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""所有 /api/* REST 路由。"""

import json
import os
import re
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from unicodedata import normalize

from flask import Blueprint, request, jsonify, Response, send_file

from config import (
    MIHE_KEY, MIHE_KEY_HINT_UI,
    BGM_DEFAULT, COVER_DIR,
)
from crawlers.book_info import get_book_info
from utils.cover import (
    remove_previous_covers_for_book,
    workflow_public_base, cover_url_for_coze_workflow,
    attach_cover_preview_to_book_info,
)
from utils.template_loader import find_preview_video, get_preview_video_url
from workflows.book.builder import generate_book_workflow
from workflows.cigarette import generate_cigarette_workflow

api_bp = Blueprint("api", __name__, url_prefix="/api")

_REPO_ROOT = Path(__file__).resolve().parent.parent
GOD_TEMPLATE_GENERATOR = _REPO_ROOT / "generate-god-template.js"


@api_bp.route("/generate_flip_intro", methods=["POST"])
def api_generate_flip_intro():
    """生成翻书片头帧序列，返回帧图片 URL 列表。"""
    data = request.json or {}
    god_name = data.get("god_name", "").strip()
    if not god_name:
        return jsonify({"error": "请输入神名"}), 400

    try:
        from utils.flip_frames import generate_flip_frames
        from workflows.god.intro_images import resolve_god_intro_images

        image_urls = resolve_god_intro_images(god_name)
        frame_urls = generate_flip_frames(image_urls)

        return jsonify({
            "success": True,
            "god_name": god_name,
            "frame_count": len(frame_urls),
            "frame_urls": frame_urls,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@api_bp.route("/search_book", methods=["POST"])
def api_search_book():
    data = request.json
    book_name = data.get("book_name", "").strip()
    if not book_name:
        return jsonify({"error": "请输入书名"}), 400

    try:
        want_trace = bool(data.get("trace")) or os.getenv(
            "CRAWLER_API_TRACE", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        book_info = get_book_info(book_name, trace=[] if want_trace else None)
        attach_cover_preview_to_book_info(book_info, request)
        return jsonify({"success": True, "book_info": book_info})
    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


@api_bp.route("/generate_book", methods=["POST"])
def api_generate_book():
    data = request.json
    book_name = data.get("book_name", "").strip()
    author = data.get("author", "").strip()
    cover = data.get("cover", "").strip()

    if not book_name:
        return jsonify({"error": "请输入书名"}), 400

    shuliang = str(data.get("shuliang", "10")).strip() or "10"
    audio_url = str(data.get("audio", "")).strip() or None
    book_script = str(data.get("book_script", "")).strip()
    visual_style = str(data.get("visual_style", "")).strip()
    voice_id = str(data.get("voice_id", "")).strip()
    url = str(data.get("url", "")).strip()
    from_link = bool(url)

    try:
        need_fetch = not author or not cover
        fetched = get_book_info(book_name) if need_fetch else {}
        cover_source_url_req = data.get("cover_source_url", "").strip()
        book_info = {
            "title": book_name,
            "author": author or (fetched.get("author") or "").strip(),
            "cover": cover or (fetched.get("cover") or "").strip(),
            "cover_source_url": (fetched.get("cover_source_url") or cover_source_url_req).strip(),
            "summary": (fetched.get("summary") or "").strip(),
        }
        pub = workflow_public_base(request.host_url.rstrip("/"))
        workflow = generate_book_workflow(
            book_info,
            public_base_url=pub,
            shuliang=shuliang,
            audio_url=audio_url,
            book_script=book_script,
            visual_style=visual_style,
            voice_id=voice_id,
            from_link=from_link,
            url=url,
        )
        book_info["cover_workflow_url"] = cover_url_for_coze_workflow(
            book_info.get("cover", ""), pub
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '', book_name)[:20]
        filename = f"每天认识一本书_{safe_name}_{timestamp}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(workflow, f, ensure_ascii=False, separators=(",", ":"))

        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/download/{filename}",
            "preview_video_url": get_preview_video_url("book"),
            "book_info": book_info,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@api_bp.route("/generate_cigarette", methods=["POST"])
def api_generate_cigarette():
    data = request.json
    cigarette_name = data.get("cigarette_name", "").strip()
    if not cigarette_name:
        return jsonify({"error": "请输入香烟名称"}), 400

    try:
        workflow = generate_cigarette_workflow(cigarette_name)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '', cigarette_name)[:20]
        filename = f"每天认识一款香烟_{safe_name}_{timestamp}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(workflow, f, ensure_ascii=False, separators=(",", ":"))

        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/download/{filename}",
            "preview_video_url": get_preview_video_url("cigarette"),
            "cigarette_name": cigarette_name,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@api_bp.route("/generate_god", methods=["POST"])
def api_generate_god():
    """以 v7 剪贴板模板为母版换神（调用 generate-god-template.js 做字节级定点替换）。"""
    data = request.json or {}
    god_name = data.get("god_name", "").strip()
    if not god_name:
        return jsonify({"error": "请输入神名"}), 400
    desc = str(data.get("desc", "")).strip()
    wenan = str(data.get("wenan", "")).strip()
    cankao = str(data.get("cankao", "")).strip()
    shuliang = str(data.get("shuliang", "")).strip()
    audio_url = str(data.get("audio", "")).strip()
    voice_id = str(data.get("voice_id", "")).strip()

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '', god_name)[:20]
        filename = f"每天认识一个神_{safe_name}_{timestamp}.txt"

        out_path = _REPO_ROOT / filename

        cmd = ["node", str(GOD_TEMPLATE_GENERATOR), god_name, "--out", str(out_path)]
        if desc:
            cmd += ["--desc", desc]
        if wenan:
            cmd += ["--wenan", wenan]
        if cankao:
            cmd += ["--cankao", cankao]
        if shuliang:
            cmd += ["--shuliang", shuliang]
        if audio_url:
            cmd += ["--audio", audio_url]
        if voice_id:
            cmd += ["--yinse", voice_id]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_REPO_ROOT),
            timeout=120,
        )
        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            return jsonify({"error": f"生成失败: {detail or 'node 生成器执行失败'}"}), 500

        warning = None
        if "不在内置形象库" in (proc.stderr or ""):
            warning = (
                f"「{god_name}」不在内置形象库，已使用通用形象描述；"
                "建议填写「主神形象描述」后重新生成，画面会更贴合神格"
            )

        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/download/{filename}",
            "preview_video_url": get_preview_video_url("god"),
            "god_name": god_name,
            "warning": warning,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@api_bp.route("/download/<filename>")
def download_file(filename):
    filepath = filename if os.path.exists(filename) else str(_REPO_ROOT / filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "文件不存在"}), 404

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    encoded_filename = quote(filename)
    safe_ascii_name = normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii") or "workflow.txt"
    return Response(
        content,
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_ascii_name}"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "Cache-Control": "no-store",
        },
    )


@api_bp.route("/preview_video/<biz_type>")
def preview_video(biz_type):
    video_path = find_preview_video(biz_type)
    if not video_path:
        return jsonify({"error": "video not found"}), 404
    return send_file(video_path, conditional=True)


@api_bp.route("/cover/<filename>")
def get_cover(filename):
    filepath = os.path.join(COVER_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "图片不存在"}), 404
    return send_file(filepath)


@api_bp.route("/upload_cover", methods=["POST"])
def upload_cover():
    """
    上传封面图片
    """
    try:
        if "cover" not in request.files:
            return jsonify({"error": "没有上传文件"}), 400

        file = request.files["cover"]
        if file.filename == "":
            return jsonify({"error": "没有选择文件"}), 400

        # 验证文件类型
        allowed_types = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
        if file.content_type not in allowed_types:
            return jsonify({"error": "只支持 JPG、PNG、WEBP 格式"}), 400

        # 生成文件名
        book_name = request.form.get("book_name", "cover")
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '', book_name)[:30]
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        # 根据文件类型确定扩展名
        ext = ".jpg"
        if "png" in file.content_type:
            ext = ".png"
        elif "webp" in file.content_type:
            ext = ".webp"

        filename = f"{safe_name}_{timestamp}{ext}"
        filepath = os.path.join(COVER_DIR, filename)

        remove_previous_covers_for_book(safe_name)
        file.save(filepath)

        cover_url = f"{request.host_url.rstrip('/')}/api/cover/{quote(filename, safe='')}"
        cover_path = str(Path(filepath).resolve())
        return jsonify({
            "success": True,
            "cover_url": cover_url,
            "cover_path": cover_path,
            "filename": filename,
        })

    except Exception as e:
        return jsonify({"error": f"上传失败: {str(e)}"}), 500


@api_bp.route("/config")
def get_config():
    return jsonify({
        "mihe_key": MIHE_KEY,
        "mihe_key_configured": bool(MIHE_KEY),
        "mihe_key_hint": MIHE_KEY_HINT_UI,
        "mihe_quota_note": "本生成器不扣米核额度；额度是否在 Coze 执行即梦时才会体现，本页无法检测。",
        "bgm_default": BGM_DEFAULT,
        "preview_video_urls": {
            "book": get_preview_video_url("book"),
            "cigarette": get_preview_video_url("cigarette"),
            "god": get_preview_video_url("god"),
        },
        "business_types": [
            {"id": "book", "name": "每天认识一本书", "description": "输入书名，自动获取书籍信息"},
            {"id": "cigarette", "name": "每天认识一款香烟", "description": "输入香烟名称，一键生成工作流"},
            {"id": "god", "name": "每天认识一个神", "description": "输入神名，一键生成工作流"},
        ],
    })
