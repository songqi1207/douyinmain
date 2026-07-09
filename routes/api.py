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
from utils.audio_probe import probe_audio_duration
from utils.coze_plugin_tools import (
    split_text_segments,
    merge_timelines,
    build_effect_infos,
)
from utils.jianying_drafts import (
    create_draft as create_jianying_draft,
    append_audios as append_draft_audios,
    append_images as append_draft_images,
    append_captions as append_draft_captions,
)
from utils.template_loader import find_preview_video, get_preview_video_url
from workflows.book.builder import generate_book_workflow
from workflows.cigarette import generate_cigarette_workflow

api_bp = Blueprint("api", __name__, url_prefix="/api")

_REPO_ROOT = Path(__file__).resolve().parent.parent
GOD_TEMPLATE_GENERATOR = _REPO_ROOT / "generate-god-template.js"
BOOK_TEMPLATE_GENERATOR = _REPO_ROOT / "generate-book-template.js"
CIG_TEMPLATE_GENERATOR = _REPO_ROOT / "generate-cigarette-template.js"


def _run_node_generator(cmd):
    """跑 node 模板生成器,返回 (ok, stderr+stdout 摘要)。"""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    return proc.returncode == 0, detail


def _external_base_url():
    public = workflow_public_base("").strip().rstrip("/")
    if public:
        return public
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
    return f"{proto}://{host}"


def _coze_list_param(data, primary_key, alias_keys=()):
    value = data.get(primary_key)
    if isinstance(value, list):
        return value
    for key in alias_keys:
        alias_value = data.get(key)
        if isinstance(alias_value, list):
            return alias_value
        if isinstance(alias_value, str) and alias_value.strip():
            try:
                parsed = json.loads(alias_value)
            except Exception:
                return []
            return parsed if isinstance(parsed, list) else []
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _coze_audio_tools_openapi(base_url):
    server_url = f"{base_url.rstrip('/')}/api"
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "抖音工作流音频工具",
            "version": "1.0.0",
            "description": "用于扣子插件的自托管音频工具。",
        },
        "servers": [
            {"url": server_url}
        ],
        "paths": {
            "/tools/get_audio_duration": {
                "post": {
                    "operationId": "get_audio_duration",
                    "summary": "获取音频时长",
                    "description": "读取本地路径或远程音频链接，返回音频时长（单位：秒）。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "mp3_url": {
                                            "type": "string",
                                            "description": "音频链接或本地文件路径。推荐优先使用这个字段。",
                                        },
                                        "url": {
                                            "type": "string",
                                            "description": "mp3_url 的别名。",
                                        },
                                        "file_path": {
                                            "type": "string",
                                            "description": "本地文件路径，可作为 mp3_url 的别名使用。",
                                        },
                                        "path": {
                                            "type": "string",
                                            "description": "本地文件路径，可作为 mp3_url 的别名使用。",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "音频时长查询结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "duration": {"type": "number", "format": "float"},
                                            "message": {"type": "string"},
                                        },
                                        "required": ["success", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


def _coze_workflow_tools_openapi(base_url):
    server_url = f"{base_url.rstrip('/')}/api"
    timeline_item_schema = {
        "type": "object",
        "properties": {
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        },
        "required": ["start", "end"],
    }
    return {
        "$schema": "https://spec.openapis.org/oas/3.0/schema/2021-09-28",
        "openapi": "3.0.3",
        "info": {
            "title": "抖音工作流辅助工具",
            "version": "1.0.0",
            "description": "用于扣子插件的自托管工作流辅助工具，包含音频、分句、时间线和特效数据处理。",
        },
        "servers": [{"url": server_url}],
        "paths": {
            "/tools/get_audio_duration": {
                "post": {
                    "tags": ["工作流工具"],
                    "operationId": "get_audio_duration",
                    "summary": "获取音频时长",
                    "description": "读取本地路径或远程音频链接，返回音频时长（单位：秒）。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "mp3_url": {"type": "string", "description": "音频链接或本地文件路径。推荐优先使用这个字段。"},
                                        "url": {"type": "string", "description": "mp3_url 的别名。"},
                                        "file_path": {"type": "string", "description": "本地文件路径，可作为 mp3_url 的别名使用。"},
                                        "path": {"type": "string", "description": "本地文件路径，可作为 mp3_url 的别名使用。"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "音频时长查询结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "duration": {"type": "number", "format": "float"},
                                            "message": {"type": "string"},
                                        },
                                        "required": ["success", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/text_splitter": {
                "post": {
                    "tags": ["工作流工具"],
                    "operationId": "text_splitter",
                    "summary": "中文智能分句",
                    "description": "将整段中文文案按标点智能切分，去掉多余符号并合并过短片段。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "需要分句处理的原始文案。"}
                                    },
                                    "required": ["text"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "分句结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "segments": {"type": "array", "items": {"type": "string"}},
                                            "message": {"type": "string"},
                                            "error": {"type": "string"},
                                        },
                                        "required": ["success", "segments"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/timeline_merge": {
                "post": {
                    "tags": ["工作流工具"],
                    "operationId": "timeline_merge",
                    "summary": "合并开场与正文时间线",
                    "description": "接收开场和正文时间线，将正文整体顺延到开场结束后。为兼容扣子导入器，这两个字段使用 JSON 字符串传入。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "pre_timeline": {"type": "string", "description": "开场时间线 JSON 字符串，例如 [{\"start\":0,\"end\":1000}]。"},
                                        "main_timeline": {"type": "string", "description": "正文时间线 JSON 字符串，例如 [{\"start\":0,\"end\":500}]。"},
                                        "gap_us": {"type": "integer", "description": "正文相对开场额外增加的间隔，单位微秒。"},
                                        "skip_us": {"type": "integer", "description": "在整体顺延后额外扣减的时长，单位微秒。"},
                                    },
                                    "required": ["pre_timeline", "main_timeline"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "时间线合并结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "timelines": {"type": "array", "items": timeline_item_schema},
                                            "main_timelines": {"type": "array", "items": timeline_item_schema},
                                            "pre_timelines": {"type": "array", "items": timeline_item_schema},
                                            "all_timeline": {"type": "array", "items": timeline_item_schema},
                                            "all_timelines": {"type": "array", "items": timeline_item_schema},
                                            "all_main_timeline": {"type": "array", "items": timeline_item_schema},
                                            "all_pre_timeline": {"type": "array", "items": timeline_item_schema},
                                            "all_complete_timeline": {"type": "array", "items": timeline_item_schema},
                                            "last_end_us": {"type": "integer"},
                                            "error": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/effect_infos": {
                "post": {
                    "tags": ["工作流工具"],
                    "operationId": "effect_infos",
                    "summary": "生成特效时间信息",
                    "description": "把特效名称列表和时间线一一对应。为兼容扣子导入器，这两个字段使用 JSON 字符串传入。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "effects": {"type": "string", "description": "特效名称 JSON 字符串，例如 [\"fade\",\"zoom\"]。"},
                                        "timelines": {"type": "string", "description": "时间线 JSON 字符串，例如 [{\"start\":0,\"end\":100}]。"},
                                    },
                                    "required": ["effects", "timelines"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "特效信息生成结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "infos": {"type": "string"},
                                            "items": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "effect": {"type": "string"},
                                                        "start": {"type": "integer"},
                                                        "end": {"type": "integer"},
                                                    },
                                                    "required": ["effect", "start", "end"],
                                                },
                                            },
                                            "count": {"type": "integer"},
                                            "error": {"type": "string"},
                                        },
                                        "required": ["infos"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/create_draft": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "create_draft",
                    "summary": "Create a local JianYing draft",
                    "description": "Create a local draft folder and return its draft_id for later add_audios/add_images/add_captions calls.",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "width": {"type": "integer", "description": "Canvas width in pixels."},
                                        "height": {"type": "integer", "description": "Canvas height in pixels."},
                                        "name": {"type": "string", "description": "Optional draft display name."},
                                        "user_id": {"type": "integer", "description": "Optional creator id."},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Draft created.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string"},
                                            "draft_name": {"type": "string"},
                                            "draft_dir": {"type": "string"},
                                            "width": {"type": "integer"},
                                            "height": {"type": "integer"},
                                            "ratio": {"type": "string"},
                                            "message": {"type": "string"},
                                        },
                                        "required": ["draft_id", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/add_audios": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "add_audios",
                    "summary": "Add audio segments to a local draft",
                    "description": "Append audio segments to a previously created local draft.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string"},
                                        "audio_infos": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "audio_url": {"type": "string"},
                                                    "start": {"type": "integer"},
                                                    "end": {"type": "integer"},
                                                    "duration": {"type": "number"},
                                                    "volume": {"type": "number"},
                                                },
                                            },
                                        },
                                    },
                                    "required": ["draft_id", "audio_infos"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Audio segments appended.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string"},
                                            "message": {"type": "string"},
                                            "track_id": {"type": "string"},
                                            "segment_ids": {"type": "array", "items": {"type": "string"}},
                                            "segment_infos": {"type": "array", "items": timeline_item_schema},
                                        },
                                        "required": ["draft_id", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/add_images": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "add_images",
                    "summary": "Add image segments to a local draft",
                    "description": "Append image segments to a previously created local draft.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string"},
                                        "alpha": {"type": "number"},
                                        "image_infos": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "image_url": {"type": "string"},
                                                    "start": {"type": "integer"},
                                                    "end": {"type": "integer"},
                                                    "duration": {"type": "number"},
                                                    "alpha": {"type": "number"},
                                                    "scale_x": {"type": "number"},
                                                    "scale_y": {"type": "number"},
                                                    "transform_x": {"type": "number"},
                                                    "transform_y": {"type": "number"},
                                                },
                                            },
                                        },
                                    },
                                    "required": ["draft_id", "image_infos"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Image segments appended.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string"},
                                            "message": {"type": "string"},
                                            "track_id": {"type": "string"},
                                            "segment_ids": {"type": "array", "items": {"type": "string"}},
                                            "segment_infos": {"type": "array", "items": timeline_item_schema},
                                        },
                                        "required": ["draft_id", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/add_captions": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "add_captions",
                    "summary": "Add captions to a local draft",
                    "description": "Append text caption segments to a previously created local draft.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string"},
                                        "captions": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "text": {"type": "string"},
                                                    "start": {"type": "integer"},
                                                    "end": {"type": "integer"},
                                                    "duration": {"type": "number"},
                                                },
                                            },
                                        },
                                        "font": {"type": "string"},
                                        "font_size": {"type": "number"},
                                        "text_color": {"type": "string"},
                                        "border_color": {"type": "string"},
                                        "alignment": {"type": "integer"},
                                        "line_spacing": {"type": "number"},
                                        "alpha": {"type": "number"},
                                        "scale_x": {"type": "number"},
                                        "scale_y": {"type": "number"},
                                        "transform_x": {"type": "number"},
                                        "transform_y": {"type": "number"},
                                        "style_text": {"type": "integer"},
                                    },
                                    "required": ["draft_id", "captions"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Caption segments appended.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string"},
                                            "message": {"type": "string"},
                                            "track_id": {"type": "string"},
                                            "segment_ids": {"type": "array", "items": {"type": "string"}},
                                            "segment_infos": {"type": "array", "items": timeline_item_schema},
                                        },
                                        "required": ["draft_id", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
    }


@api_bp.route("/tools/get_audio_duration", methods=["GET", "POST"])
def api_get_audio_duration():
    """Local replacement for the third-party get_audio_duration plugin."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args
    target = (
        str(data.get("mp3_url", "")).strip()
        or str(data.get("url", "")).strip()
        or str(data.get("file_path", "")).strip()
        or str(data.get("path", "")).strip()
    )
    if not target:
        return jsonify({
            "success": False,
            "message": "missing mp3_url/url/file_path/path",
        }), 400

    try:
        duration = probe_audio_duration(target)
        return jsonify({
            "success": True,
            "duration": duration,
            "message": "ok",
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
        }), 400


@api_bp.route("/tools/text_splitter", methods=["GET", "POST"])
def api_text_splitter():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({
            "success": False,
            "segments": [],
            "message": "missing text",
            "error": "missing text",
        }), 400

    return jsonify({
        "success": True,
        "segments": split_text_segments(text),
        "message": "ok",
        "error": "",
    })


@api_bp.route("/tools/timeline_merge", methods=["GET", "POST"])
def api_timeline_merge():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    pre_timeline = _coze_list_param(data, "pre_timeline", ("pre_timeline_json",))
    main_timeline = _coze_list_param(data, "main_timeline", ("main_timeline_json",))
    if not isinstance(pre_timeline, list) or not isinstance(main_timeline, list):
        return jsonify({"error": "pre_timeline and main_timeline must be lists"}), 400

    return jsonify(merge_timelines(
        pre_timeline=pre_timeline,
        main_timeline=main_timeline,
        gap_us=data.get("gap_us", 0),
        skip_us=data.get("skip_us", 0),
    ))


@api_bp.route("/tools/effect_infos", methods=["GET", "POST"])
def api_effect_infos():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    effects = _coze_list_param(data, "effects", ("effects_json",))
    timelines = _coze_list_param(data, "timelines", ("timelines_json",))
    if not isinstance(effects, list) or not isinstance(timelines, list):
        return jsonify({"error": "effects and timelines must be lists"}), 400

    return jsonify(build_effect_infos(effects, timelines))


@api_bp.route("/tools/create_draft", methods=["GET", "POST"])
def api_create_draft():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    try:
        return jsonify(create_jianying_draft(
            width=data.get("width", 1920),
            height=data.get("height", 1080),
            name=str(data.get("name", "")).strip(),
            user_id=data.get("user_id"),
        ))
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@api_bp.route("/tools/add_audios", methods=["GET", "POST"])
def api_add_audios():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = str(data.get("draft_id", "")).strip()
    audio_infos = _coze_list_param(data, "audio_infos", ("audio_infos_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id"}), 400
    if not isinstance(audio_infos, list):
        return jsonify({"message": "audio_infos must be a list"}), 400

    try:
        return jsonify(append_draft_audios(draft_id, audio_infos))
    except Exception as e:
        return jsonify({"draft_id": draft_id, "message": str(e)}), 400


@api_bp.route("/tools/add_images", methods=["GET", "POST"])
def api_add_images():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = str(data.get("draft_id", "")).strip()
    image_infos = _coze_list_param(data, "image_infos", ("image_infos_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id"}), 400
    if not isinstance(image_infos, list):
        return jsonify({"message": "image_infos must be a list"}), 400

    try:
        return jsonify(append_draft_images(
            draft_id,
            image_infos,
            alpha=data.get("alpha"),
        ))
    except Exception as e:
        return jsonify({"draft_id": draft_id, "message": str(e)}), 400


@api_bp.route("/tools/add_captions", methods=["GET", "POST"])
def api_add_captions():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = str(data.get("draft_id", "")).strip()
    captions = _coze_list_param(data, "captions", ("captions_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id"}), 400
    if not isinstance(captions, list):
        return jsonify({"message": "captions must be a list"}), 400

    try:
        return jsonify(append_draft_captions(
            draft_id,
            captions,
            alpha=data.get("alpha"),
            alignment=data.get("alignment"),
            border_color=str(data.get("border_color", "")).strip(),
            font=str(data.get("font", "")).strip(),
            font_size=data.get("font_size"),
            line_spacing=data.get("line_spacing"),
            scale_x=data.get("scale_x"),
            scale_y=data.get("scale_y"),
            style_text=data.get("style_text"),
            text_color=str(data.get("text_color", "#FFFFFF")).strip() or "#FFFFFF",
            transform_x=data.get("transform_x"),
            transform_y=data.get("transform_y"),
        ))
    except Exception as e:
        return jsonify({"draft_id": draft_id, "message": str(e)}), 400


@api_bp.route("/openapi/coze_audio_tools.json")
def coze_audio_tools_openapi():
    """Minimal OpenAPI spec kept for Coze import compatibility."""
    return jsonify(_coze_audio_tools_openapi(_external_base_url()))


@api_bp.route("/openapi/coze_workflow_tools.json")
def coze_workflow_tools_openapi():
    """Extended OpenAPI spec for self-hosted workflow helper tools."""
    return jsonify(_coze_workflow_tools_openapi(_external_base_url()))


@api_bp.route("/openapi/test.json")
def coze_openapi_test():
    return jsonify({
        "openapi": "3.0.3",
        "info": {
            "title": "test",
            "version": "1.0.0",
        },
        "servers": [{"url": _external_base_url().rstrip("/")}],
        "paths": {},
    })


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
    """以书籍 v1 母版换书（node generate-book-template.js 字节级定点替换）。"""
    data = request.json or {}
    book_name = data.get("book_name", "").strip()
    if not book_name:
        return jsonify({"error": "请输入书名"}), 400

    author = str(data.get("author", "")).strip()
    cover = str(data.get("cover", "")).strip()
    shuliang = str(data.get("shuliang", "")).strip()
    audio_url = str(data.get("audio", "")).strip()
    book_script = str(data.get("book_script", "")).strip()
    visual_style = str(data.get("visual_style", "")).strip()
    voice_id = str(data.get("voice_id", "")).strip()
    texiao = str(data.get("texiao", "")).strip()
    url = str(data.get("url", "")).strip()

    # 「从链接生成」仍走旧版书单带货模板（v1 母版没有抖音/小红书取链节点）
    if url:
        return _generate_book_from_link(data, book_name, author, cover,
                                        shuliang or "10", audio_url or None,
                                        book_script, visual_style, voice_id, url)

    try:
        # 补作者/摘要用于丰富解说方向；爬虫失败不阻断生成
        try:
            fetched = get_book_info(book_name) or {}
        except Exception:
            fetched = {}
        author = author or (fetched.get("author") or "").strip()
        summary = (fetched.get("summary") or "").strip()

        wenan = ""
        if summary:
            prefix = f"《{book_name}》"
            if author:
                prefix += f"，作者{author}"
            wenan = f"{prefix}。{summary}"[:500]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[^\w一-鿿]', '', book_name)[:20]
        filename = f"每天认识一本书_{safe_name}_{timestamp}.txt"
        out_path = _REPO_ROOT / filename

        cmd = ["node", str(BOOK_TEMPLATE_GENERATOR), book_name, "--out", str(out_path)]
        if author:
            cmd += ["--author", author]
        if visual_style:
            cmd += ["--desc", visual_style]
        if wenan:
            cmd += ["--wenan", wenan]
        if book_script:
            cmd += ["--cankao", book_script]
        if shuliang:
            cmd += ["--shuliang", shuliang]
        if audio_url:
            cmd += ["--audio", audio_url]
        if voice_id:
            cmd += ["--yinse", voice_id]
        if texiao:
            cmd += ["--texiao", texiao]

        ok, detail = _run_node_generator(cmd)
        if not ok or not out_path.exists():
            return jsonify({"error": f"生成失败: {detail[-500:] or 'node 生成器执行失败'}"}), 500

        warning = None
        if "不在内置画面气质库" in detail:
            warning = (
                f"「{book_name}」不在内置画面气质库，已使用通用画面风格；"
                "建议填写「画面风格」后重新生成，画面会更贴合这本书"
            )

        return jsonify({
            "success": True,
            "filename": filename,
            "download_url": f"/api/download/{filename}",
            "preview_video_url": get_preview_video_url("book"),
            "book_info": {"title": book_name, "author": author, "summary": summary},
            "warning": warning,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


def _generate_book_from_link(data, book_name, author, cover, shuliang,
                             audio_url, book_script, visual_style, voice_id, url):
    """旧版书单带货管线：抖音/小红书链接取文案改写（v1 母版不含取链节点）。"""
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
            from_link=True,
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
    """老红塔山模板 + 情感独白增量改造（2026-07-08 回归老管线）。"""
    data = request.json or {}
    cigarette_name = data.get("cigarette_name", "").strip()
    if not cigarette_name:
        return jsonify({"error": "请输入香烟名称"}), 400
    cover_url = str(data.get("cover", "")).strip()
    voice_id = str(data.get("voice_id", "")).strip()

    try:
        workflow, warning = generate_cigarette_workflow(cigarette_name, cover_url=cover_url, voice_id=voice_id)

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
            "warning": warning,
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
