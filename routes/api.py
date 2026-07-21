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
from urllib.parse import parse_qs, quote, urlsplit
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
    align_text_to_audio,
    build_audio_infos,
    build_audio_timelines,
    build_caption_infos,
    split_text_segments,
    build_image_infos,
    build_keyframes_infos,
    build_rolling_effect,
    merge_timelines,
    collect_audio_links,
    build_effect_infos,
    build_wenan_timeline_range,
)
from utils.draft_key_importer import (
    AssetDownloadError,
    KeyValidationError,
    import_draft_key,
)
from utils.jianying_drafts import (
    create_draft as create_jianying_draft,
    append_audios as append_draft_audios,
    append_images as append_draft_images,
    append_captions as append_draft_captions,
    append_effects as append_draft_effects,
    append_keyframes as append_draft_keyframes,
    get_draft_info as get_jianying_draft_info,
    export_draft_archive as export_jianying_draft_archive,
    import_remote_draft as import_remote_jianying_draft,
)
from utils.local_media_generation import (
    generate_placeholder_image,
    generated_file_path,
    synthesize_speech,
)
from utils.template_loader import find_preview_video, get_preview_video_url
from workflows.book.builder import generate_book_workflow
from workflows.cigarette import generate_cigarette_workflow
from workflows.draft_key_recorder import add_draft_key_recorder, generate_recorded_workflow

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


def _draft_url_for_id(draft_id: str) -> str:
    return f"{_external_base_url().rstrip('/')}/api/tools/get_draft?draft_id={quote(str(draft_id or '').strip())}"


def _draft_id_from_url(draft_url) -> str:
    raw = str(draft_url or "").strip()
    if not raw:
        return ""
    try:
        query = parse_qs(urlsplit(raw).query)
    except Exception:
        return ""
    return str((query.get("draft_id") or [""])[0]).strip()


def _resolve_request_draft_id(data) -> str:
    draft_id = str(data.get("draft_id", "")).strip()
    if draft_id:
        return draft_id
    return _draft_id_from_url(data.get("draft_url"))


def _attach_draft_url(payload, draft_id: str):
    body = dict(payload or {})
    if draft_id:
        body.setdefault("draft_id", draft_id)
        body.setdefault("draft_url", _draft_url_for_id(draft_id))
    return body


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
                    "summary": "创建本地剪映草稿",
                    "description": "创建本地剪映草稿目录，并返回 draft_id 与 draft_url，供后续 add_audios、add_images、add_captions 等工具继续写入素材。",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "width": {"type": "integer", "description": "画布宽度，单位像素，例如 1080。"},
                                        "height": {"type": "integer", "description": "画布高度，单位像素，例如 1920。"},
                                        "name": {"type": "string", "description": "草稿名称，可选；不传时自动生成。"},
                                        "user_id": {"type": "integer", "description": "创建人 ID，可选；仅用于透传记录。"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "草稿创建结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string", "description": "草稿唯一标识。"},
                                            "draft_url": {"type": "string", "description": "草稿访问地址，可直接传给兼容 capcut-mate 风格的后续工具调用。"},
                                            "draft_name": {"type": "string", "description": "草稿名称。"},
                                            "draft_dir": {"type": "string", "description": "草稿目录的本地绝对路径。"},
                                            "width": {"type": "integer", "description": "草稿画布宽度。"},
                                            "height": {"type": "integer", "description": "草稿画布高度。"},
                                            "ratio": {"type": "string", "description": "画布比例，例如 9:16。"},
                                            "message": {"type": "string", "description": "执行结果说明。"},
                                        },
                                        "required": ["draft_id", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/get_draft": {
                "get": {
                    "tags": ["workflow-tools"],
                    "operationId": "get_draft",
                    "summary": "查询本地剪映草稿",
                    "description": "根据 draft_id 或 draft_url 查询本地草稿信息，并返回 Windows 可访问路径。",
                    "parameters": [
                        {"name": "draft_id", "in": "query", "schema": {"type": "string"}, "description": "草稿 ID。"},
                        {"name": "draft_url", "in": "query", "schema": {"type": "string"}, "description": "草稿地址；与 draft_id 二选一即可。"},
                    ],
                    "responses": {
                        "200": {
                            "description": "草稿查询结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string", "description": "草稿唯一标识。"},
                                            "draft_url": {"type": "string", "description": "草稿访问地址。"},
                                            "draft_name": {"type": "string", "description": "草稿名称。"},
                                            "draft_dir": {"type": "string", "description": "草稿目录的本地绝对路径。"},
                                            "width": {"type": "integer", "description": "草稿画布宽度。"},
                                            "height": {"type": "integer", "description": "草稿画布高度。"},
                                            "ratio": {"type": "string", "description": "画布比例，例如 9:16。"},
                                            "duration": {"type": "integer", "description": "当前草稿总时长，单位微秒。"},
                                            "message": {"type": "string", "description": "执行结果说明。"},
                                        },
                                        "required": ["draft_id", "draft_dir", "message"],
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
                    "summary": "向本地草稿追加音频片段",
                    "description": "把一个或多个音频片段写入已创建的本地剪映草稿中。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                        "draft_url": {"type": "string", "description": "目标草稿的 draft_url。与 draft_id 二选一即可。"},
                                        "audio_infos": {
                                            "type": "array",
                                            "description": "音频片段列表，每一项代表一段要插入草稿的音频。",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "audio_url": {"type": "string", "description": "音频链接或本地文件路径。"},
                                                    "start": {"type": "integer", "description": "片段开始时间，单位微秒。"},
                                                    "end": {"type": "integer", "description": "片段结束时间，单位微秒。"},
                                                    "duration": {"type": "number", "description": "音频时长，单位秒；可选。"},
                                                    "volume": {"type": "number", "description": "音量倍率，例如 1.0 表示原始音量。"},
                                                },
                                            },
                                        },
                                    },
                                    "required": ["audio_infos"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "音频片段写入结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                            "draft_url": {"type": "string", "description": "目标草稿的 draft_url。"},
                                            "message": {"type": "string", "description": "执行结果说明。"},
                                            "track_id": {"type": "string", "description": "写入的音频轨道 ID。"},
                                            "segment_ids": {"type": "array", "description": "新建音频片段 ID 列表。", "items": {"type": "string"}},
                                            "audio_ids": {"type": "array", "description": "新建音频素材 ID 列表。", "items": {"type": "string"}},
                                            "segment_infos": {"type": "array", "description": "写入后的片段时间信息。", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "片段 ID。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}}, "required": ["id", "start", "end"]}},
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
                    "summary": "向本地草稿追加图片片段",
                    "description": "把一个或多个图片片段写入已创建的本地剪映草稿中。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                        "draft_url": {"type": "string", "description": "目标草稿的 draft_url。与 draft_id 二选一即可。"},
                                        "alpha": {"type": "number", "description": "默认透明度，取值通常为 0 到 1。"},
                                        "image_infos": {
                                            "type": "array",
                                            "description": "图片片段列表，每一项代表一张要插入草稿的图片。",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "image_url": {"type": "string", "description": "图片链接或本地文件路径。"},
                                                    "start": {"type": "integer", "description": "片段开始时间，单位微秒。"},
                                                    "end": {"type": "integer", "description": "片段结束时间，单位微秒。"},
                                                    "duration": {"type": "number", "description": "片段时长，单位秒；可选。"},
                                                    "alpha": {"type": "number", "description": "当前片段透明度。"},
                                                    "scale_x": {"type": "number", "description": "X 方向缩放比例。"},
                                                    "scale_y": {"type": "number", "description": "Y 方向缩放比例。"},
                                                    "transform_x": {"type": "number", "description": "X 方向位移。"},
                                                    "transform_y": {"type": "number", "description": "Y 方向位移。"},
                                                },
                                            },
                                        },
                                    },
                                    "required": ["image_infos"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "图片片段写入结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                            "draft_url": {"type": "string", "description": "目标草稿的 draft_url。"},
                                            "message": {"type": "string", "description": "执行结果说明。"},
                                            "track_id": {"type": "string", "description": "写入的图片轨道 ID。"},
                                            "segment_ids": {"type": "array", "description": "新建图片片段 ID 列表。", "items": {"type": "string"}},
                                            "segment_infos": {"type": "array", "description": "写入后的片段时间信息。", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "片段 ID。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}}, "required": ["id", "start", "end"]}},
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
                    "summary": "向本地草稿追加字幕片段",
                    "description": "把一个或多个字幕片段写入已创建的本地剪映草稿中。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                        "draft_url": {"type": "string", "description": "目标草稿的 draft_url。与 draft_id 二选一即可。"},
                                        "captions": {
                                            "type": "array",
                                            "description": "字幕片段列表，每一项代表一段字幕。",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "text": {"type": "string", "description": "字幕文本内容。"},
                                                    "start": {"type": "integer", "description": "字幕开始时间，单位微秒。"},
                                                    "end": {"type": "integer", "description": "字幕结束时间，单位微秒。"},
                                                    "duration": {"type": "number", "description": "字幕时长，单位秒；可选。"},
                                                },
                                            },
                                        },
                                        "font": {"type": "string", "description": "字体名称，可选。"},
                                        "font_size": {"type": "number", "description": "字号大小。"},
                                        "text_color": {"type": "string", "description": "文字颜色，支持十六进制颜色值。"},
                                        "border_color": {"type": "string", "description": "描边颜色，支持十六进制颜色值。"},
                                        "alignment": {"type": "integer", "description": "对齐方式，通常 0/1/2 分别表示左对齐、居中、右对齐。"},
                                        "line_spacing": {"type": "number", "description": "行间距。"},
                                        "alpha": {"type": "number", "description": "透明度，取值通常为 0 到 1。"},
                                        "scale_x": {"type": "number", "description": "X 方向缩放比例。"},
                                        "scale_y": {"type": "number", "description": "Y 方向缩放比例。"},
                                        "transform_x": {"type": "number", "description": "X 方向位移。"},
                                        "transform_y": {"type": "number", "description": "Y 方向位移。"},
                                        "style_text": {"type": "integer", "description": "样式文本模式或预设编号，可选。"},
                                    },
                                    "required": ["captions"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "字幕片段写入结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                            "draft_url": {"type": "string", "description": "目标草稿的 draft_url。"},
                                            "message": {"type": "string", "description": "执行结果说明。"},
                                            "track_id": {"type": "string", "description": "写入的字幕轨道 ID。"},
                                            "segment_ids": {"type": "array", "description": "新建字幕片段 ID 列表。", "items": {"type": "string"}},
                                            "segment_infos": {"type": "array", "description": "写入后的片段时间信息。", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "片段 ID。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}}, "required": ["id", "start", "end"]}},
                                        },
                                        "required": ["draft_id", "message"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/audio_link_collector": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "audio_link_collector",
                    "summary": "从批量输出中提取音频链接",
                    "description": "从插件批量输出结果中提取可用的音频链接列表。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "outputList": {"type": "array", "description": "上游节点返回的批量输出数组。", "items": {"type": "object", "properties": {"code": {"type": "number", "description": "上游节点状态码，可选。"}, "msg": {"type": "string", "description": "上游节点消息，可选。"}, "data": {"type": "object", "description": "上游节点数据对象，内部通常包含 link/url 等音频地址字段。", "properties": {"link": {"type": "string", "description": "音频链接，可选。"}, "url": {"type": "string", "description": "兼容字段，可选。"}, "audio_url": {"type": "string", "description": "兼容字段，可选。"}}}, "link": {"type": "string", "description": "直接返回的音频链接，可选。"}, "url": {"type": "string", "description": "兼容字段，可选。"}, "audio_url": {"type": "string", "description": "兼容字段，可选。"}}}},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "音频链接提取结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"links": {"type": "array", "description": "提取出的音频链接列表。", "items": {"type": "string"}}}}}}}},
                }
            },
            "/tools/audio_timelines": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "audio_timelines",
                    "summary": "根据音频链接生成顺序时间线",
                    "description": "按音频顺序依次计算时间线，可用于后续 add_audios 或字幕对齐。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "links": {"type": "array", "description": "音频链接列表。", "items": {"type": "string"}},
                                        "gap_us": {"type": "integer", "description": "相邻音频之间额外插入的间隔，单位微秒。"},
                                    },
                                    "required": ["links"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "音频时间线生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"timelines": {"type": "array", "description": "生成的音频时间线。", "items": timeline_item_schema}, "all_timelines": {"type": "array", "description": "完整时间线结果。", "items": timeline_item_schema}}}}}}},
                }
            },
            "/tools/audio_infos": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "audio_infos",
                    "summary": "根据音频链接和时间线生成音频信息",
                    "description": "把音频链接与时间线组合成 add_audios 可直接使用的 payload。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "mp3_urls": {"type": "array", "description": "音频链接列表。", "items": {"type": "string"}},
                                        "timelines": {"type": "array", "description": "与音频一一对应的时间线。", "items": timeline_item_schema},
                                        "audio_effect": {"type": "string", "description": "音频效果名称，可选。"},
                                        "volume": {"type": "number", "description": "统一音量倍率，可选。"},
                                    },
                                    "required": ["mp3_urls", "timelines"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "音频信息生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"infos": {"type": "string", "description": "可直接传给 add_audios 的 JSON 字符串。"}, "items": {"type": "array", "description": "解析后的音频信息数组。", "items": {"type": "object", "properties": {"audio_url": {"type": "string", "description": "音频地址。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}, "duration": {"type": "integer", "description": "时长，单位微秒。"}, "audio_effect": {"type": "string", "description": "音频效果名称。"}, "volume": {"type": "number", "description": "音量倍率。"}}}}, "count": {"type": "integer", "description": "生成条目数量。"}, "error": {"type": "string", "description": "错误信息，无错误时为空字符串。"}}}}}}},
                }
            },
            "/tools/caption_infos": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "caption_infos",
                    "summary": "根据文本和时间线生成字幕信息",
                    "description": "把文案和时间线组合成 add_captions 可直接使用的 payload。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "texts": {"type": "array", "description": "字幕文本数组。", "items": {"type": "string"}},
                                        "timelines": {"type": "array", "description": "与字幕逐条对应的时间线。", "items": timeline_item_schema},
                                        "font_size": {"type": "integer", "description": "字幕字号，可选。"},
                                    },
                                    "required": ["texts", "timelines"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "字幕信息生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"infos": {"type": "string", "description": "可直接传给 add_captions 的 JSON 字符串。"}, "items": {"type": "array", "description": "解析后的字幕信息数组。", "items": {"type": "object", "properties": {"text": {"type": "string", "description": "字幕文本。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}, "font_size": {"type": "integer", "description": "字号。"}}}}, "count": {"type": "integer", "description": "生成条目数量。"}, "error": {"type": "string", "description": "错误信息，无错误时为空字符串。"}}}}}}},
                }
            },
            "/tools/imgs_infos": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "imgs_infos",
                    "summary": "根据图片链接和时间线生成图片信息",
                    "description": "把图片链接和时间线组合成 add_images 可直接使用的 payload。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "imgs": {"type": "array", "description": "图片链接列表。", "items": {"type": "string"}},
                                        "timelines": {"type": "array", "description": "与图片逐条对应的时间线。", "items": timeline_item_schema},
                                        "out_animation_duration": {"type": "integer", "description": "出场动画时长，单位微秒，可选。"},
                                    },
                                    "required": ["imgs", "timelines"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "图片信息生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"infos": {"type": "string", "description": "可直接传给 add_images 的 JSON 字符串。"}, "items": {"type": "array", "description": "解析后的图片信息数组。", "items": {"type": "object", "properties": {"image_url": {"type": "string", "description": "图片地址。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}, "out_animation_duration": {"type": "integer", "description": "出场动画时长，单位微秒。"}}}}, "count": {"type": "integer", "description": "生成条目数量。"}, "error": {"type": "string", "description": "错误信息，无错误时为空字符串。"}}}}}}},
                }
            },
            "/tools/keyframes_infos": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "keyframes_infos",
                    "summary": "根据片段时间线生成关键帧信息",
                    "description": "把关键帧类型、偏移量和值组合成 add_keyframes 可直接使用的 payload。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "ctype": {"type": "string", "description": "关键帧类型，例如 x、y、scale_x、scale_y。"},
                                        "offsets": {"type": "string", "description": "关键帧偏移量列表，通常为 JSON 字符串。"},
                                        "segment_infos": {"type": "array", "description": "目标片段信息列表。", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "片段 ID。"}, "start": {"type": "integer", "description": "片段开始时间，单位微秒。"}, "end": {"type": "integer", "description": "片段结束时间，单位微秒。"}}, "required": ["id", "start", "end"]}},
                                        "values": {"type": "string", "description": "关键帧取值列表，通常为 JSON 字符串。"},
                                        "width": {"type": "integer", "description": "画布宽度，可选。"},
                                        "height": {"type": "integer", "description": "画布高度，可选。"},
                                    },
                                    "required": ["ctype", "offsets", "segment_infos", "values"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "关键帧信息生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"keyframes_infos": {"type": "string", "description": "可直接传给 add_keyframes 的 JSON 字符串。"}, "items": {"type": "array", "description": "解析后的关键帧数组。", "items": {"type": "object", "properties": {"offset": {"type": "integer", "description": "关键帧偏移时间，单位微秒。"}, "property": {"type": "string", "description": "关键帧属性名。"}, "segment_id": {"type": "string", "description": "目标片段 ID。"}, "value": {"type": "number", "description": "关键帧数值。"}}}}, "count": {"type": "integer", "description": "生成条目数量。"}, "error": {"type": "string", "description": "错误信息，无错误时为空字符串。"}}}}}}},
                }
            },
            "/tools/rolling_effect": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "rolling_effect",
                    "summary": "根据时长和文本生成快闪时间线",
                    "description": "根据时长列表和文本列表生成开场快闪效果所需的时间线数据。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "duration_list": {"type": "array", "description": "每段快闪持续时长列表，单位微秒。", "items": {"type": "integer"}},
                                        "str_list": {"type": "array", "description": "与时长对应的文本列表。", "items": {"type": "string"}},
                                    },
                                    "required": ["duration_list", "str_list"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "快闪时间线生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"timelines": {"type": "array", "description": "分段时间线列表。", "items": timeline_item_schema}, "subject_arr": {"type": "array", "description": "快闪文本列表。", "items": {"type": "string"}}, "all_timeline": {"type": "array", "description": "完整时间线列表。", "items": timeline_item_schema}, "error": {"type": "string", "description": "错误信息，无错误时为空字符串。"}}}}}}},
                }
            },
            "/tools/wenan_timeline_range": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "wenan_timeline_range",
                    "summary": "合并文案与时间线范围",
                    "description": "将文案数组与时间线数组按顺序合并，生成每段文案对应的时间范围。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "timelines": {"type": "array", "description": "时间线数组。", "items": timeline_item_schema},
                                        "wenan": {"type": "array", "description": "文案数组。", "items": {"type": "string"}},
                                    },
                                    "required": ["timelines", "wenan"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "文案时间线合并结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"wenanTimeline": {"type": "array", "description": "文案与时间线组合后的结果数组。", "items": {"type": "object", "properties": {"content": {"type": "string", "description": "当前时间段对应的文案内容。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}}, "required": ["content", "start", "end"]}}, "error": {"type": "string", "description": "错误信息，无错误时为空字符串。"}}}}}}},
                }
            },
            "/tools/align_text_to_audio": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "align_text_to_audio",
                    "summary": "按音频时长对齐文本分句",
                    "description": "先对文本进行分句，再按音频总时长比例生成对应字幕时间线。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "需要对齐的原始文案。"},
                                        "audio_url": {"type": "string", "description": "用于对齐的音频链接或本地文件路径。"},
                                        "max_chars_per_line": {"type": "integer", "description": "每行最大字数，可选；用于控制分句粒度。"},
                                    },
                                    "required": ["text", "audio_url"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "文本与音频对齐结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "texts": {
                                                "type": "array",
                                                "description": "分句后的文本数组。",
                                                "items": {"type": "string"},
                                            },
                                            "timelines": {
                                                "type": "array",
                                                "description": "与文本对应的时间线数组。",
                                                "items": timeline_item_schema,
                                            },
                                            "data": {
                                                "type": "object",
                                                "description": "附加调试信息，例如总时长等。",
                                                "properties": {
                                                    "audio_url": {"type": "string", "description": "用于对齐的音频地址。"},
                                                    "duration": {"type": "number", "description": "音频总时长，单位秒。"},
                                                    "segments": {
                                                        "type": "array",
                                                        "description": "文本与时间线的配对明细。",
                                                        "items": {
                                                            "type": "object",
                                                            "properties": {
                                                                "text": {"type": "string", "description": "分句文本。"},
                                                                "start": {"type": "integer", "description": "开始时间，单位微秒。"},
                                                                "end": {"type": "integer", "description": "结束时间，单位微秒。"},
                                                            },
                                                            "required": ["text", "start", "end"],
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/add_keyframes": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "add_keyframes",
                    "summary": "向草稿片段追加关键帧",
                    "description": "给已有草稿片段写入关键帧数据，例如位置、缩放等动画信息。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                        "draft_url": {"type": "string", "description": "目标草稿的 draft_url。与 draft_id 二选一即可。"},
                                        "keyframes": {
                                            "type": "array",
                                            "description": "关键帧列表。",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "segment_id": {"type": "string", "description": "目标片段 ID。"},
                                                    "id": {"type": "string", "description": "segment_id 的兼容别名。"},
                                                    "offset": {"type": "integer", "description": "关键帧时间偏移，单位微秒。"},
                                                    "property": {"type": "string", "description": "关键帧属性名，例如 KFTypePositionX。"},
                                                    "property_type": {"type": "string", "description": "property 的兼容别名。"},
                                                    "value": {"type": "number", "description": "关键帧数值。"},
                                                },
                                            },
                                        },
                                    },
                                    "required": ["keyframes"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "关键帧写入结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"draft_id": {"type": "string", "description": "目标草稿的 draft_id。"}, "draft_url": {"type": "string", "description": "目标草稿的 draft_url。"}, "message": {"type": "string", "description": "执行结果说明。"}, "applied": {"type": "integer", "description": "成功写入的关键帧数量。"}}}}}}},
                }
            },
            "/tools/add_effects": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "add_effects",
                    "summary": "向本地草稿追加特效片段",
                    "description": "把特效片段写入本地剪映草稿，用于开场或主体特效轨道。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "draft_id": {"type": "string", "description": "目标草稿的 draft_id。"},
                                        "draft_url": {"type": "string", "description": "目标草稿的 draft_url。与 draft_id 二选一即可。"},
                                        "effect_infos": {
                                            "type": "array",
                                            "description": "特效片段列表。",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "effect": {"type": "string", "description": "特效名称。"},
                                                    "name": {"type": "string", "description": "effect 的兼容别名。"},
                                                    "effect_id": {"type": "string", "description": "特效 ID 或名称兼容字段。"},
                                                    "start": {"type": "integer", "description": "开始时间，单位微秒。"},
                                                    "end": {"type": "integer", "description": "结束时间，单位微秒。"},
                                                    "duration": {"type": "integer", "description": "持续时长，单位微秒；未传 end 时可使用该字段。"},
                                                },
                                            },
                                        },
                                    },
                                    "required": ["effect_infos"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "特效片段写入结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"draft_id": {"type": "string", "description": "目标草稿的 draft_id。"}, "draft_url": {"type": "string", "description": "目标草稿的 draft_url。"}, "message": {"type": "string", "description": "执行结果说明。"}, "effect_ids": {"type": "array", "description": "新建特效素材 ID 列表。", "items": {"type": "string"}}, "segment_ids": {"type": "array", "description": "新建特效片段 ID 列表。", "items": {"type": "string"}}, "segment_infos": {"type": "array", "description": "写入后的特效片段信息。", "items": {"type": "object", "properties": {"id": {"type": "string", "description": "片段 ID。"}, "start": {"type": "integer", "description": "开始时间，单位微秒。"}, "end": {"type": "integer", "description": "结束时间，单位微秒。"}, "effect": {"type": "string", "description": "特效名称。"}}, "required": ["id", "start", "end", "effect"]}}, "track_id": {"type": "string", "description": "写入的特效轨道 ID。"}}}}}}},
                }
            },
            "/tools/speech_synthesis": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "speech_synthesis",
                    "summary": "本地语音合成",
                    "description": "使用本地 Windows 语音能力生成音频；当前实现包含占位回退逻辑，不等同于官方 Coze 语音合成。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "description": "要合成的文本内容。"},
                                        "voice_id": {"type": "string", "description": "音色 ID，可选；当前仅作兼容透传。"},
                                        "emotion": {"type": "string", "description": "情绪参数，可选；当前仅作兼容透传。"},
                                        "emotion_scale": {"type": "integer", "description": "情绪强度，可选；当前仅作兼容透传。"},
                                        "speed_ratio": {"type": "number", "description": "语速倍率，可选。"},
                                    },
                                    "required": ["text"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "语音合成结果。",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "code": {"type": "number", "description": "状态码，0 表示成功。"},
                                            "data": {
                                                "type": "object",
                                                "description": "返回数据。",
                                                "properties": {
                                                    "duration": {"type": "number", "description": "生成音频时长，单位秒。"},
                                                    "link": {"type": "string", "description": "生成音频的访问链接。"},
                                                },
                                            },
                                            "log_id": {"type": "string", "description": "日志追踪 ID。"},
                                            "msg": {"type": "string", "description": "执行结果说明。"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/tools/jimeng_generate_image": {
                "post": {
                    "tags": ["workflow-tools"],
                    "operationId": "jimeng_generate_image",
                    "summary": "本地占位生图",
                    "description": "根据提示词生成本地占位图片，用于替代即梦生图节点；当前不是即梦官方真实出图能力。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "prompt": {"type": "string", "description": "图片提示词。"},
                                        "key": {"type": "string", "description": "兼容字段，可选；当前未实际使用。"},
                                        "model": {"type": "string", "description": "模型名称，可选；当前未实际使用。"},
                                        "ratio": {"type": "string", "description": "图片比例，例如 1:1、9:16，可选。"},
                                    },
                                    "required": ["prompt"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "占位图片生成结果。", "content": {"application/json": {"schema": {"type": "object", "properties": {"message": {"type": "string", "description": "执行结果说明。"}, "task_id": {"type": "string", "description": "任务 ID。"}, "url": {"type": "string", "description": "生成图片的访问链接。"}}}}}}},
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


@api_bp.route("/tools/audio_link_collector", methods=["GET", "POST"])
def api_audio_link_collector():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    output_list = _coze_list_param(data, "outputList", ("outputList_json",))
    return jsonify(collect_audio_links(output_list))


@api_bp.route("/tools/audio_timelines", methods=["GET", "POST"])
def api_audio_timelines():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    links = _coze_list_param(data, "links", ("links_json",))
    if not isinstance(links, list):
        return jsonify({"message": "links must be a list"}), 400

    try:
        return jsonify(build_audio_timelines(links, gap_us=data.get("gap_us", 0)))
    except Exception as e:
        return jsonify({"message": str(e), "timelines": [], "all_timelines": []}), 400


@api_bp.route("/tools/audio_infos", methods=["GET", "POST"])
def api_audio_infos():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    mp3_urls = _coze_list_param(data, "mp3_urls", ("mp3_urls_json", "links_json", "links"))
    timelines = _coze_list_param(data, "timelines", ("timelines_json",))
    if not isinstance(mp3_urls, list) or not isinstance(timelines, list):
        return jsonify({"message": "mp3_urls and timelines must be lists"}), 400

    return jsonify(build_audio_infos(
        mp3_urls,
        timelines,
        audio_effect=str(data.get("audio_effect", "")).strip(),
        volume=data.get("volume"),
    ))


@api_bp.route("/tools/caption_infos", methods=["GET", "POST"])
def api_caption_infos():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    texts = _coze_list_param(data, "texts", ("texts_json",))
    timelines = _coze_list_param(data, "timelines", ("timelines_json",))
    if not isinstance(texts, list) or not isinstance(timelines, list):
        return jsonify({"message": "texts and timelines must be lists"}), 400

    return jsonify(build_caption_infos(texts, timelines, font_size=data.get("font_size")))


@api_bp.route("/tools/imgs_infos", methods=["GET", "POST"])
def api_imgs_infos():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    imgs = _coze_list_param(data, "imgs", ("imgs_json",))
    timelines = _coze_list_param(data, "timelines", ("timelines_json",))
    if not isinstance(imgs, list) or not isinstance(timelines, list):
        return jsonify({"message": "imgs and timelines must be lists"}), 400

    return jsonify(build_image_infos(
        imgs,
        timelines,
        out_animation_duration=data.get("out_animation_duration"),
    ))


@api_bp.route("/tools/keyframes_infos", methods=["GET", "POST"])
def api_keyframes_infos():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    segment_infos = _coze_list_param(data, "segment_infos", ("segment_infos_json",))
    if not isinstance(segment_infos, list):
        return jsonify({"message": "segment_infos must be a list"}), 400

    return jsonify(build_keyframes_infos(
        segment_infos=segment_infos,
        ctype=str(data.get("ctype", "")).strip(),
        offsets=str(data.get("offsets", "")).strip(),
        values=str(data.get("values", "")).strip(),
        width=data.get("width"),
        height=data.get("height"),
    ))


@api_bp.route("/tools/rolling_effect", methods=["GET", "POST"])
def api_rolling_effect():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    duration_list = _coze_list_param(data, "duration_list", ("duration_list_json",))
    str_list = _coze_list_param(data, "str_list", ("str_list_json",))
    if not isinstance(duration_list, list) or not isinstance(str_list, list):
        return jsonify({"message": "duration_list and str_list must be lists"}), 400

    return jsonify(build_rolling_effect(duration_list, str_list))


@api_bp.route("/tools/wenan_timeline_range", methods=["GET", "POST"])
def api_wenan_timeline_range():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    timelines = _coze_list_param(data, "timelines", ("timelines_json",))
    wenan = _coze_list_param(data, "wenan", ("wenan_json",))
    if not isinstance(timelines, list) or not isinstance(wenan, list):
        return jsonify({"message": "timelines and wenan must be lists"}), 400

    return jsonify(build_wenan_timeline_range(timelines, wenan))


@api_bp.route("/tools/align_text_to_audio", methods=["GET", "POST"])
def api_align_text_to_audio():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    text = str(data.get("text", "")).strip()
    audio_url = str(data.get("audio_url", "")).strip()
    if not text or not audio_url:
        return jsonify({"message": "missing text/audio_url", "texts": [], "timelines": [], "data": {}}), 400

    try:
        return jsonify(align_text_to_audio(
            text=text,
            audio_url=audio_url,
            max_chars_per_line=data.get("max_chars_per_line", 14),
        ))
    except Exception as e:
        return jsonify({"message": str(e), "texts": [], "timelines": [], "data": {}}), 400


@api_bp.route("/tools/create_draft", methods=["GET", "POST"])
def api_create_draft():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    try:
        payload = create_jianying_draft(
            width=data.get("width", 1920),
            height=data.get("height", 1080),
            name=str(data.get("name", "")).strip(),
            user_id=data.get("user_id"),
        )
        return jsonify(_attach_draft_url(payload, payload.get("draft_id", "")))
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@api_bp.route("/tools/get_draft", methods=["GET", "POST"])
def api_get_draft():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400

    try:
        payload = get_jianying_draft_info(draft_id)
        return jsonify(_attach_draft_url(payload, payload.get("draft_id", draft_id)))
    except Exception as e:
        return jsonify({"draft_id": draft_id, "message": str(e)}), 400


@api_bp.route("/tools/export_draft_archive", methods=["GET", "POST"])
def api_export_draft_archive():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400

    try:
        payload = export_jianying_draft_archive(draft_id)
        archive_path = payload["archive_path"]
        return send_file(
            archive_path,
            as_attachment=True,
            attachment_filename=f"{payload['draft_id']}.zip",
            mimetype="application/zip",
            conditional=True,
        )
    except Exception as e:
        return jsonify({"draft_id": draft_id, "message": str(e)}), 400


@api_bp.route("/tools/import_remote_draft", methods=["POST"])
def api_import_remote_draft():
    data = request.get_json(silent=True) or {}
    draft_id = str(data.get("draft_id", "")).strip()
    if not draft_id:
        return jsonify({"message": "missing draft_id"}), 400

    try:
        payload = import_remote_jianying_draft(
            draft_id=draft_id,
            remote_base_url=str(data.get("remote_base_url", "")).strip(),
            package_url=str(data.get("package_url", "")).strip(),
            force=data.get("force", False),
        )
        return jsonify(_attach_draft_url(payload, payload.get("draft_id", draft_id)))
    except Exception as e:
        return jsonify({"draft_id": draft_id, "message": str(e)}), 400


@api_bp.route("/tools/add_audios", methods=["GET", "POST"])
def api_add_audios():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    audio_infos = _coze_list_param(data, "audio_infos", ("audio_infos_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400
    if not isinstance(audio_infos, list):
        return jsonify({"message": "audio_infos must be a list"}), 400

    try:
        payload = append_draft_audios(draft_id, audio_infos)
        return jsonify(_attach_draft_url(payload, draft_id))
    except Exception as e:
        return jsonify(_attach_draft_url({"message": str(e)}, draft_id)), 400


@api_bp.route("/tools/add_images", methods=["GET", "POST"])
def api_add_images():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    image_infos = _coze_list_param(data, "image_infos", ("image_infos_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400
    if not isinstance(image_infos, list):
        return jsonify({"message": "image_infos must be a list"}), 400

    try:
        payload = append_draft_images(
            draft_id,
            image_infos,
            alpha=data.get("alpha"),
        )
        return jsonify(_attach_draft_url(payload, draft_id))
    except Exception as e:
        return jsonify(_attach_draft_url({"message": str(e)}, draft_id)), 400


@api_bp.route("/tools/add_captions", methods=["GET", "POST"])
def api_add_captions():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    captions = _coze_list_param(data, "captions", ("captions_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400
    if not isinstance(captions, list):
        return jsonify({"message": "captions must be a list"}), 400

    try:
        payload = append_draft_captions(
            draft_id,
            captions,
            alpha=data.get("alpha"),
            alignment=data.get("alignment"),
            border_color=str(data.get("border_color", "")).strip(),
            font=str(data.get("font", "")).strip(),
            font_size=data.get("font_size"),
            letter_spacing=data.get("letter_spacing"),
            line_spacing=data.get("line_spacing"),
            scale_x=data.get("scale_x"),
            scale_y=data.get("scale_y"),
            style_text=data.get("style_text"),
            text_color=str(data.get("text_color", "#FFFFFF")).strip() or "#FFFFFF",
            transform_x=data.get("transform_x"),
            transform_y=data.get("transform_y"),
        )
        return jsonify(_attach_draft_url(payload, draft_id))
    except Exception as e:
        return jsonify(_attach_draft_url({"message": str(e)}, draft_id)), 400


@api_bp.route("/tools/add_keyframes", methods=["GET", "POST"])
def api_add_keyframes():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    keyframes = _coze_list_param(data, "keyframes", ("keyframes_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400
    if not isinstance(keyframes, list):
        return jsonify({"message": "keyframes must be a list"}), 400

    try:
        payload = append_draft_keyframes(draft_id, keyframes)
        return jsonify(_attach_draft_url(payload, draft_id))
    except Exception as e:
        return jsonify(_attach_draft_url({"message": str(e)}, draft_id)), 400


@api_bp.route("/tools/add_effects", methods=["GET", "POST"])
def api_add_effects():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    draft_id = _resolve_request_draft_id(data)
    effect_infos = _coze_list_param(data, "effect_infos", ("effect_infos_json",))
    if not draft_id:
        return jsonify({"message": "missing draft_id or draft_url"}), 400
    if not isinstance(effect_infos, list):
        return jsonify({"message": "effect_infos must be a list"}), 400

    try:
        payload = append_draft_effects(draft_id, effect_infos)
        return jsonify(_attach_draft_url(payload, draft_id))
    except Exception as e:
        return jsonify(_attach_draft_url({"message": str(e)}, draft_id)), 400


@api_bp.route("/tools/create_draft_from_key", methods=["POST"])
def api_create_draft_from_key():
    data = request.get_json(silent=True) or {}

    key = data.get("key", data)
    if isinstance(key, str):
        try:
            key = json.loads(key)
        except json.JSONDecodeError:
            return jsonify({"message": "key 不是合法 JSON 字符串", "errors": ["invalid key_json"]}), 400
    if isinstance(data.get("key_json"), str):
        try:
            key = json.loads(data["key_json"])
        except json.JSONDecodeError:
            return jsonify({"message": "key_json 不是合法 JSON 字符串", "errors": ["invalid key_json"]}), 400

    force = str(request.args.get("force", data.get("force", ""))).strip().lower() in ("1", "true", "yes")
    dry_run = str(request.args.get("dry_run", data.get("dry_run", ""))).strip().lower() in ("1", "true", "yes")

    try:
        return jsonify(import_draft_key(key, force=force, dry_run=dry_run))
    except KeyValidationError as e:
        return jsonify({"message": "key 校验失败", "errors": e.errors}), 400
    except AssetDownloadError as e:
        return jsonify({"message": "素材下载失败", "failed_urls": e.failed}), 502
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@api_bp.route("/tools/speech_synthesis", methods=["GET", "POST"])
def api_speech_synthesis():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    text = str(data.get("text", "")).strip()
    if not text:
        return jsonify({"code": 1, "data": {}, "log_id": "", "msg": "missing text"}), 400

    try:
        return jsonify(synthesize_speech(
            text=text,
            base_url=_external_base_url(),
            voice_id=str(data.get("voice_id", "")).strip(),
            speed_ratio=data.get("speed_ratio"),
            emotion=str(data.get("emotion", "")).strip(),
            emotion_scale=data.get("emotion_scale"),
        ))
    except Exception as e:
        return jsonify({"code": 1, "data": {}, "log_id": "", "msg": str(e)}), 400


@api_bp.route("/tools/jimeng_generate_image", methods=["GET", "POST"])
def api_jimeng_generate_image():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"message": "missing prompt", "task_id": "", "url": ""}), 400

    try:
        return jsonify(generate_placeholder_image(
            prompt=prompt,
            base_url=_external_base_url(),
            ratio=str(data.get("ratio", "16:9")).strip() or "16:9",
            model=str(data.get("model", "")).strip(),
            key=str(data.get("key", "")).strip(),
        ))
    except Exception as e:
        return jsonify({"message": str(e), "task_id": "", "url": ""}), 400


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
        source_path = out_path.with_name(f".{out_path.name}.source.json")

        cmd = ["node", str(BOOK_TEMPLATE_GENERATOR), book_name, "--out", str(source_path)]
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
        if not ok or not source_path.exists():
            source_path.unlink(missing_ok=True)
            return jsonify({"error": f"生成失败: {detail[-500:] or 'node 生成器执行失败'}"}), 500

        try:
            conversion = generate_recorded_workflow(
                source_path,
                out_path,
                workflow_name="书单工作流_米核插件+draft_key记录",
                draft_name=f"书单_{book_name}",
                run_prefix="book_recorded_",
            )
        except Exception as conversion_error:
            out_path.unlink(missing_ok=True)
            return jsonify({"error": f"生成 draft_key 工作流失败: {conversion_error}"}), 500
        finally:
            source_path.unlink(missing_ok=True)

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
            "workflow_output": "draft_id+draft_key",
            "draft_call_count": len(conversion["calls"]),
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
        conversion = add_draft_key_recorder(
            workflow,
            workflow_name="书单工作流_米核插件+draft_key记录",
            draft_name=f"书单_{book_name}",
            run_prefix="book_recorded_",
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
            "workflow_output": "draft_id+draft_key",
            "draft_call_count": len(conversion["calls"]),
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
        conversion = add_draft_key_recorder(
            workflow,
            workflow_name="香烟工作流_米核插件+draft_key记录",
            draft_name=f"香烟_{cigarette_name}",
            run_prefix="cigarette_recorded_",
        )

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
            "workflow_output": "draft_id+draft_key",
            "draft_call_count": len(conversion["calls"]),
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
        source_path = out_path.with_name(f".{out_path.name}.source.json")

        cmd = ["node", str(GOD_TEMPLATE_GENERATOR), god_name, "--out", str(source_path)]
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
        if proc.returncode != 0 or not source_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            source_path.unlink(missing_ok=True)
            return jsonify({"error": f"生成失败: {detail or 'node 生成器执行失败'}"}), 500

        try:
            conversion = generate_recorded_workflow(
                source_path,
                out_path,
                workflow_name="神工作流_米核插件+draft_key记录",
                draft_name=f"神话解说_{god_name}",
                run_prefix="god_recorded_",
            )
        except Exception as conversion_error:
            out_path.unlink(missing_ok=True)
            return jsonify({"error": f"生成 draft_key 工作流失败: {conversion_error}"}), 500
        finally:
            source_path.unlink(missing_ok=True)

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
            "workflow_output": "draft_id+draft_key",
            "draft_call_count": len(conversion["calls"]),
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


@api_bp.route("/generated/<kind>/<filename>")
def generated_media(kind, filename):
    if kind not in {"audio", "image"}:
        return jsonify({"error": "invalid generated media kind"}), 404
    filepath = generated_file_path(kind, filename)
    if not filepath.exists():
        return jsonify({"error": "generated file not found"}), 404
    return send_file(filepath, conditional=True)


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
