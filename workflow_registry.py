"""Business workflow registry and public schemas.

The registry deliberately separates browser-visible inputs from provider secrets.
API keys and provider workflow IDs are resolved by the worker from environment
variables and are never returned by the public API.
"""

from __future__ import annotations

import os
from copy import deepcopy

from business_workflows import FALLBACK, WORKFLOW_METADATA, load_business_workflows


DEMO_CODES = {"G247", "G218", "G159"}
REFERENCE_TEMPLATE_CODES = {"G259", "G258", "G168", "G45", "G263", "G129", "G159", "G222"}
PROVIDER_CODES = DEMO_CODES | REFERENCE_TEMPLATE_CODES
LOCAL_CODES = {"OWN01", "OWN02", "OWN03"}
PUBLISHED_WORKFLOW_ENV_ALIASES = {"OWN03": "COZE_WORKFLOW_GOD"}


def published_workflow_id(code: str) -> str:
    normalized = str(code or "").upper()
    primary = (os.getenv(f"COZE_WORKFLOW_{normalized}") or "").strip()
    alias = PUBLISHED_WORKFLOW_ENV_ALIASES.get(normalized, "")
    return primary or ((os.getenv(alias) or "").strip() if alias else "")

TEMPLATE_INPUT_SCHEMAS = {
    "OWN01": [{"name": "theme", "label": "书籍主题 / 书名", "type": "text", "required": True, "placeholder": "例如：活着"}],
    "OWN02": [{"name": "theme", "label": "香烟主题 / 名称", "type": "text", "required": True, "placeholder": "例如：红塔山"}],
    "OWN03": [{"name": "theme", "label": "神话主题 / 神名", "type": "text", "required": True, "placeholder": "例如：哪吒"}],
    "G259": [{"name": "theme", "label": "视频主题", "type": "text", "required": True, "placeholder": "例如：买彩票中了五百万的一生"}],
    "G258": [{"name": "theme", "label": "亲子教育主题", "type": "text", "required": True, "placeholder": "例如：孩子写作业拖拉怎么办"}],
    "G168": [{"name": "theme", "label": "小说推文主题", "type": "text", "required": True, "placeholder": "例如：重生后我成为商业大亨"}],
    "G45": [{"name": "theme", "label": "女性心理学主题", "type": "text", "required": True, "placeholder": "例如：为什么越懂事越容易内耗"}],
    "G263": [{"name": "theme", "label": "商品与带货主题", "type": "text", "required": True, "placeholder": "例如：夏季防晒衣轻薄透气"}],
    "G129": [{"name": "theme", "label": "养生主题", "type": "text", "required": True, "placeholder": "例如：夏季祛湿养生"}],
    "G159": [{"name": "theme", "label": "减肥主题", "type": "text", "required": True, "placeholder": "例如：坚持运动第30天"}],
    "G222": [{"name": "theme", "label": "商业案例主题", "type": "text", "required": True, "placeholder": "例如：蜜雪冰城靠什么赚钱"}],
}

LOCAL_WORKFLOWS = [
    {
        "code": "OWN01",
        "name": "每天认识一本书",
        "description": "输入书名、作者和画面方向，生成可直接导入扣子的书单荐书工作流文件。",
        "tags": ["自有", "书单", "起号"],
        "stats": {"views": 0, "favorites": 0, "downloads": 0},
        "created_at": "2026-07-19T00:00:00+08:00",
    },
    {
        "code": "OWN02",
        "name": "每天认识一款香烟",
        "description": "输入香烟名称生成情感独白、烟盒轮播和剪映草稿编排工作流文件。",
        "tags": ["自有", "香烟", "起号"],
        "stats": {"views": 0, "favorites": 0, "downloads": 0},
        "created_at": "2026-07-19T00:00:00+08:00",
    },
    {
        "code": "OWN03",
        "name": "每天认识一个神",
        "description": "输入神名、形象描述和分镜数量，生成中国神话解说视频工作流文件。",
        "tags": ["自有", "神话", "起号"],
        "stats": {"views": 0, "favorites": 0, "downloads": 0},
        "created_at": "2026-07-19T00:00:00+08:00",
    },
]

INPUT_SCHEMAS = {
    "OWN01": [
        {"name": "book_name", "label": "书名", "type": "text", "required": True, "placeholder": "例如：活着"},
        {"name": "author", "label": "作者", "type": "text", "required": False, "placeholder": "可选"},
        {"name": "scene_count", "label": "正文配图数量", "type": "number", "required": True, "default": 6, "min": 1, "max": 22},
        {"name": "visual_style", "label": "画面风格", "type": "textarea", "required": False, "placeholder": "例如：电影感、低饱和、现实主义"},
        {"name": "book_script", "label": "参考文案", "type": "textarea", "required": False, "placeholder": "不填写则由工作流自动生成"},
        {"name": "voice_id", "label": "配音音色 ID", "type": "text", "required": False},
    ],
    "OWN02": [
        {"name": "cigarette_name", "label": "香烟名称", "type": "text", "required": True, "placeholder": "例如：中华、红塔山、荷花"},
        {"name": "cover_url", "label": "烟盒图片地址", "type": "text", "required": False, "placeholder": "图库没有该品牌时填写"},
        {"name": "voice_id", "label": "配音音色 ID", "type": "text", "required": False},
    ],
    "OWN03": [
        {"name": "god_name", "label": "神名", "type": "text", "required": True, "placeholder": "例如：哪吒、妈祖、二郎神"},
        {"name": "description", "label": "主神形象描述", "type": "textarea", "required": False, "placeholder": "内置形象库没有时可补充"},
        {"name": "scene_count", "label": "分镜数量", "type": "number", "required": True, "default": 10, "min": 1, "max": 22},
        {"name": "script", "label": "自定义解说文案", "type": "textarea", "required": False},
        {"name": "audio_url", "label": "背景音乐地址", "type": "text", "required": False},
        {"name": "voice_id", "label": "配音音色 ID", "type": "text", "required": False},
    ],
    "G247": [
        {
            "name": "name",
            "label": "商品名称和卖点",
            "type": "textarea",
            "required": True,
            "placeholder": "例如：轻量休闲鞋，透气、耐磨、适合通勤",
        },
        {
            "name": "image",
            "label": "商品图片",
            "type": "image",
            "required": True,
            "multiple": True,
            "max_files": 8,
            "accept": ["image/jpeg", "image/png", "image/webp"],
        },
    ],
    "G218": [
        {
            "name": "title",
            "label": "养生主题",
            "type": "text",
            "required": True,
            "placeholder": "例如：夏季祛湿食谱",
        },
        {
            "name": "num",
            "label": "图文数量",
            "type": "number",
            "required": True,
            "default": 5,
            "min": 1,
            "max": 10,
        },
    ],
    "G159": [
        {
            "name": "title",
            "label": "减肥主题",
            "type": "text",
            "required": True,
            "placeholder": "例如：坚持运动第30天",
        },
        {
            "name": "left_text",
            "label": "左下角文字",
            "type": "text",
            "required": True,
            "default": "自律",
        },
        {
            "name": "right_text",
            "label": "右下角文字",
            "type": "text",
            "required": True,
            "default": "坚持",
        },
        {
            "name": "text",
            "label": "自定义文案",
            "type": "textarea",
            "required": False,
            "placeholder": "不填写则由工作流自动生成",
        },
    ],
    "G259": [
        {
            "name": "content_mode",
            "label": "内容方向",
            "type": "select",
            "required": True,
            "default": "human_insight",
            "options": [
                {"label": "社会现象 / 人性洞察", "value": "human_insight"},
                {"label": "某某的一生", "value": "life_story"},
            ],
        },
        {
            "name": "title",
            "label": "主题",
            "type": "text",
            "required": True,
            "placeholder": "例如：买彩票中了五百万的一生",
        },
        {
            "name": "text",
            "label": "自定义文案",
            "type": "textarea",
            "required": False,
            "placeholder": "不填写则由工作流根据主题自动生成",
        },
        {
            "name": "voice_notice",
            "label": "配音说明",
            "type": "notice",
            "required": False,
            "default": "默认使用工作流官方配音；外部配音 API Key 由后台配置。",
        },
    ],
    "G258": [
        {
            "name": "title",
            "label": "亲子教育主题",
            "type": "text",
            "required": True,
            "placeholder": "例如：孩子写作业拖拉，父母应该怎么办",
        },
        {
            "name": "text",
            "label": "自定义文案",
            "type": "textarea",
            "required": False,
            "placeholder": "不填写则自动生成文案",
        },
        {
            "name": "voice_notice",
            "label": "配音说明",
            "type": "notice",
            "required": False,
            "default": "默认使用工作流官方配音；外部配音 API Key 由后台配置。",
        },
    ],
    "G168": [
        {
            "name": "novel_document",
            "label": "小说文案 Word 文档",
            "type": "file",
            "required": True,
            "accept": [
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "text/plain",
                ".docx",
                ".txt",
            ],
        },
    ],
    "G45": [
        {
            "name": "title",
            "label": "女性心理学主题",
            "type": "text",
            "required": True,
            "placeholder": "例如：为什么越懂事的女生越容易内耗",
        },
        {
            "name": "ip_name",
            "label": "个人 IP 名称",
            "type": "text",
            "required": False,
            "placeholder": "显示在视频底部",
        },
        {
            "name": "text",
            "label": "自定义文案",
            "type": "textarea",
            "required": False,
            "placeholder": "不填写则自动生成中英文双字幕文案",
        },
        {
            "name": "left_text",
            "label": "左侧节目名",
            "type": "text",
            "required": False,
            "placeholder": "例如：女性成长系列",
        },
    ],
    "G07": [
        {"name": "theme", "label": "图文主题", "type": "text", "required": True},
    ],
    "G90": [
        {"name": "theme", "label": "减肥建议主题", "type": "text", "required": True},
    ],
}

OUTPUT_TYPES = {
    "OWN01": "draft",
    "OWN02": "draft",
    "OWN03": "draft",
    "G247": "image",
    "G218": "image",
    "G159": "video",
    "G259": "video",
    "G258": "video",
    "G168": "video",
    "G45": "video",
    "G246": "video",
    "G263": "video",
    "G129": "video",
    "G222": "video",
}


def _provider_mode() -> str:
    return (os.getenv("WORKFLOW_PROVIDER_MODE") or "demo").strip().lower()


def _normalize_item(category: str, item: dict) -> dict:
    code = str(item.get("code") or "").upper()
    name = str(item.get("name") or code).strip()
    if name.upper().startswith(code):
        name = name[len(code):].strip(" ·-—") or code
    preview = bool(item.get("preview"))
    provider_configured = bool(published_workflow_id(code)) and bool(os.getenv("COZE_API_TOKEN"))
    published_local = code in LOCAL_CODES and provider_configured
    render_configured = bool((os.getenv("WORKFLOW_RENDER_API_URL") or "").strip())
    template_builder = (code in LOCAL_CODES and not published_local) or (
        code in REFERENCE_TEMPLATE_CODES
        and (os.getenv("WORKFLOW_BUILD_MODE") or "template").strip().lower() == "template"
    )
    enabled = (
        template_builder
        or (published_local and render_configured)
        or
        (code in DEMO_CODES and _provider_mode() == "demo")
        or (code in PROVIDER_CODES and provider_configured)
    )
    return {
        "code": code,
        "name": name,
        "description": item.get("description") or "工作流正在整理中。",
        "category": category,
        "categories": [category],
        "tags": list(item.get("tags") or [category]),
        "preview": preview,
        "preview_mime": item.get("preview_mime") or "",
        "preview_url": f"/api/v1/workflows/{code}/preview?category={category}" if preview else None,
        # Counts from the source site are intentionally not reused. FastAPI
        # overlays this with events and favorites persisted by our own site.
        "stats": {"views": 0, "favorites": 0, "downloads": 0, "runs": 0},
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at") or item.get("created_at"),
        "status": "online" if enabled else "coming_soon",
        "input_schema": deepcopy(
            TEMPLATE_INPUT_SCHEMAS.get(code, []) if template_builder else INPUT_SCHEMAS.get(code, [])
        ),
        "output_type": OUTPUT_TYPES.get(code, "draft"),
        "generation_mode": "workflow_template" if template_builder else "draft" if published_local else "video",
    }


def workflow_catalog() -> dict[str, list[dict]]:
    raw = load_business_workflows()
    catalog = {
        category: [_normalize_item(category, item) for item in items]
        for category, items in raw.items()
    }
    catalog["自有工作流"] = [_normalize_item("自有工作流", item) for item in LOCAL_WORKFLOWS]
    return catalog


def list_workflows(category: str = "全部") -> list[dict]:
    catalog = workflow_catalog()
    if category in catalog:
        return catalog[category]

    merged: dict[str, dict] = {}
    for current_category, items in catalog.items():
        for item in items:
            code = item["code"]
            if code not in merged:
                merged[code] = deepcopy(item)
            elif current_category not in merged[code]["categories"]:
                merged[code]["categories"].append(current_category)
    return list(merged.values())


def get_workflow(code: str, category: str | None = None) -> dict | None:
    code = str(code or "").upper()
    candidates = list_workflows(category or "全部")
    selected = next((item for item in candidates if item["code"] == code), None)
    if selected:
        return selected

    # Keep the already-wired demo providers callable even when the storefront
    # intentionally displays only one ranked workflow per category.
    if code in DEMO_CODES:
        for fallback_category, items in FALLBACK.items():
            match = next(((item_code, name) for item_code, name in items if item_code.upper() == code), None)
            if match and (category is None or category == fallback_category):
                _, name = match
                metadata = WORKFLOW_METADATA.get(code, {})
                return _normalize_item(
                    fallback_category,
                    {
                        "code": code,
                        "name": name,
                        "description": metadata.get("description") or "工作流正在整理中。",
                        "tags": metadata.get("tags") or [fallback_category],
                        "stats": metadata.get("stats") or {"views": 0, "favorites": 0, "downloads": 0},
                    },
                )
    return None


def category_summary() -> list[dict]:
    catalog = workflow_catalog()
    return [
        {"name": category, "count": len(catalog.get(category, []))}
        for category in ("起号", "电商", "养生", "减肥", "财经", "自有工作流")
    ]
