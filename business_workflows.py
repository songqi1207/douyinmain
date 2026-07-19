"""四个业务分类的工作流目录。

优先读取本地下载的 manifest；部署时即使不带 285MB 的参考附件，也能用
下面的轻量回退目录正常展示页面。
"""

import json
import mimetypes
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DOWNLOAD_ROOT = ROOT / "downloads" / "reference_workflows"
PREVIEW_ROOT = ROOT / "static" / "workflow-previews"

FALLBACK = {
    "起号": [
        ("G259", "社会现象人性洞察视频"),
        ("G258", "家庭亲子教育儿童成长视频"),
        ("G168", "一键生成小说推文视频开头有特效"),
        ("G45", "小红书热门女性心理学视频"),
    ],
    "电商": [
        ("G263", "自动生成短剧类带货视频"), ("G247", "鞋类商品电商详情页"),
        ("G246", "参考视频动作模仿迁移图生视频"), ("G245", "一键自动生成商品电商详情页"),
        ("G234", "Seedance2.0生成商品带货视频"), ("G226", "爆款视频自动复刻二创"),
        ("G225", "人物图片衣服图片自动换装"), ("G131", "自动生成皮包类商品电商详情页"),
        ("G126", "搜索真实风景视频匹配文案画面"), ("G82", "视频人物换装换衣服"),
        ("G65", "视频中人物替换成图片中的人物"), ("G49", "一键自动生成商品宣传展示视频"),
        ("G34", "图片人物换装多张图支持内衣"), ("G33", "商品图片一键自动更换背景"),
        ("G31", "人物模特一键自动换装生成视频"), ("G24", "视频换人换成图片中的人物"),
    ],
    "养生": [
        ("G218", "自动生成小红书健康养生图文"), ("G156", "自动生成养生建议动态视频"),
        ("G143", "一键生成小红书养生食材图文"), ("G129", "一键生成古风动画养生动态视频"),
        ("G90", "健康生活减肥建议视频"), ("G83", "指定字数生成养生风格文案视频"),
        ("G76", "自动生成养生类动态视频"), ("G67", "传统古风中式健康养生知识视频"),
        ("G07", "一键生成小红书养生图文笔记"),
    ],
    "减肥": [("G159", "减肥励志大师督促激励视频"), ("G90", "健康生活减肥建议视频")],
    "财经": [],
}


WORKFLOW_METADATA = {
    "G259": {
        "description": "输入主题自动生成社会现象、人性洞察或“某某的一生”类文案视频，也可以使用自定义文案。",
        "tags": ["起号", "人性", "视频"],
        "stats": {"views": 44, "favorites": 1, "downloads": 4},
    },
    "G258": {
        "description": "输入主题生成家庭亲子教育、儿童成长类文案视频，支持自定义文案和配音来源。",
        "tags": ["起号", "教育", "育儿"],
        "stats": {"views": 38, "favorites": 2, "downloads": 14},
    },
    "G168": {
        "description": "上传小说 Word 文档生成小说推文视频，开头包含主角和文字特效。",
        "tags": ["起号", "小说推文", "视频"],
        "stats": {"views": 5, "favorites": 0, "downloads": 6},
    },
    "G45": {
        "description": "输入主题生成女性心理学视频，可设置个人 IP 名称，并显示中英文双字幕。",
        "tags": ["起号", "心理学", "视频"],
        "stats": {"views": 7, "favorites": 0, "downloads": 4},
    },
}


def _manifest_items(category):
    path = DOWNLOAD_ROOT / category / "manifest.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("workflows", [])
    except (OSError, ValueError):
        return []


def load_business_workflows():
    result = {}
    for category, fallback in FALLBACK.items():
        manifest = _manifest_items(category)
        if manifest:
            result[category] = [
                _public_item(category, item)
                for item in manifest
            ]
        else:
            result[category] = [
                {
                    "code": code,
                    "name": name,
                    "description": WORKFLOW_METADATA.get(code, {}).get(
                        "description", "已纳入业务目录，等待接入后台生成 provider。"
                    ),
                    "tags": WORKFLOW_METADATA.get(code, {}).get("tags", [category]),
                    "source_url": None,
                    "files": [],
                    "preview": bool(_static_preview(category, code)),
                    "preview_mime": "image/jpeg" if _static_preview(category, code) else "",
                    "stats": WORKFLOW_METADATA.get(code, {}).get(
                        "stats", {"views": 0, "favorites": 0, "downloads": 0}
                    ),
                }
                for code, name in fallback
            ]
    return result


def _public_item(category, item):
    """只向浏览器暴露展示元数据，不暴露飞书附件 token。"""
    files = item.get("files", []) or []
    preview = next(
        (file for file in files if str(file.get("mime", "")).startswith(("video/", "image/"))),
        None,
    )
    static_preview = _static_preview(category, item.get("code"))
    public_files = [
        {"name": file.get("name"), "mime": file.get("mime"), "size": file.get("size", 0)}
        for file in files
    ]
    code = item.get("code")
    return {
        "code": code,
        "name": item.get("name"),
        "description": item.get("description") or "参考工作流已下载，可接入对应 provider。",
        "tags": item.get("tags", []) or [category],
        "files": public_files,
        "preview": bool(static_preview or preview),
        "preview_mime": "image/jpeg" if static_preview else preview.get("mime") if preview else "",
        "stats": item.get("stats") or {"views": 0, "favorites": 0, "downloads": len(files)},
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at") or item.get("created_at"),
    }


def find_preview_asset(category, code):
    """返回本地预览文件路径；找不到时返回 None。"""
    static_preview = _static_preview(category, code)
    if static_preview:
        return static_preview, mimetypes.guess_type(static_preview.name)[0] or "image/jpeg"
    for item in _manifest_items(category):
        if str(item.get("code", "")).lower() != str(code).lower():
            continue
        for file in item.get("files", []) or []:
            if not str(file.get("mime", "")).startswith(("video/", "image/")):
                continue
            relative = file.get("path")
            if not relative:
                continue
            path = (DOWNLOAD_ROOT / relative).resolve()
            if DOWNLOAD_ROOT.resolve() in path.parents and path.is_file():
                return path, str(file.get("mime", "application/octet-stream"))
    return None


def find_workflow_downloads(category, code):
    """Return the two catalog downloads that are safe to expose to members."""
    if category not in FALLBACK or not re.fullmatch(r"G\d+", str(code or ""), re.IGNORECASE):
        return []

    normalized_code = str(code).upper()
    category_root = (DOWNLOAD_ROOT / category).resolve()
    workflow_root = (category_root / normalized_code).resolve()
    if category_root not in workflow_root.parents or not workflow_root.is_dir():
        return []

    downloads = []
    safe_json = (workflow_root / "workflow.json").resolve()
    if workflow_root in safe_json.parents and safe_json.is_file():
        downloads.append(
            {
                "kind": "json",
                "label": "下载工作流 JSON",
                "filename": f"{normalized_code}-workflow.json",
                "path": safe_json,
                "mime": "application/json",
                "size": safe_json.stat().st_size,
            }
        )

    packages = sorted(workflow_root.glob("*.zip"))
    if packages:
        package = packages[0].resolve()
        if workflow_root in package.parents and package.is_file():
            downloads.append(
                {
                    "kind": "package",
                    "label": "下载扣子导入包 ZIP",
                    "filename": package.name,
                    "path": package,
                    "mime": "application/zip",
                    "size": package.stat().st_size,
                }
            )
    return downloads


def _static_preview(category, code):
    """Resolve only catalog-owned lightweight previews, never arbitrary paths."""
    if category not in FALLBACK or not re.fullmatch(r"G\d+", str(code or ""), re.IGNORECASE):
        return None
    category_root = (PREVIEW_ROOT / category).resolve()
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = (category_root / f"{str(code).upper()}{suffix}").resolve()
        if category_root in candidate.parents and candidate.is_file():
            return candidate
    return None
