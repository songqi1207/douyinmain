#!/usr/bin/env python3
"""Build a compact, machine-readable acceptance report for a draft_key import."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any


_LIST_FIELDS = {
    "add_audios": ("audio_infos", "infos", "audios"),
    "add_images": ("image_infos", "infos", "imgs", "images"),
    "add_videos": ("video_infos", "infos", "videos"),
    "add_captions": ("captions", "infos", "texts"),
    "add_keyframes": ("keyframes", "infos"),
    "add_effects": ("effect_infos", "infos", "effects"),
}
_ASSET_FIELDS = ("audio_url", "video_url", "image_url", "img", "url", "path", "file_path")
_TITLE_CALL_IDS = {"slide_a", "slide_b", "slide_c", "title_lock", "top_label", "corner_tip"}
_UNIFORM_SCALE_PROPERTIES = {"UNIFORM_SCALE", "KFTypeUniformScale"}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _call_items(call: dict[str, Any]) -> list[dict[str, Any]]:
    params = call.get("params") or {}
    for field in _LIST_FIELDS.get(str(call.get("tool") or ""), ()):
        if field in params:
            return [item for item in _as_list(params[field]) if isinstance(item, dict)]
    return []


def _effective(call: dict[str, Any], item: dict[str, Any], field: str) -> Any:
    value = item.get(field)
    if value not in (None, ""):
        return value
    return (call.get("params") or {}).get(field)


def _counter_dict(values: Counter) -> dict[str, int]:
    return {str(name): count for name, count in sorted(values.items(), key=lambda pair: str(pair[0]))}


def build_draft_key_acceptance_report(
    key: dict[str, Any],
    import_report: dict[str, Any],
    *,
    profile: str = "god",
) -> dict[str, Any]:
    """Inspect the portable intent and the completed local import.

    A failed acceptance check does not delete the generated draft.  The caller
    can surface the report while keeping the draft available for inspection.
    """

    calls = [call for call in _as_list(key.get("calls")) if isinstance(call, dict)]
    tool_calls: Counter[str] = Counter()
    tool_items: Counter[str] = Counter()
    asset_urls: set[str] = set()
    fonts: Counter[str] = Counter()
    text_colors: Counter[str] = Counter()
    text_animations: Counter[str] = Counter()
    image_animations: Counter[str] = Counter()
    keyframe_properties: Counter[str] = Counter()
    effect_titles: Counter[str] = Counter()
    title_font_mismatches: list[dict[str, str]] = []
    main_caption_styles: list[dict[str, str]] = []

    for call in calls:
        tool = str(call.get("tool") or "")
        call_id = str(call.get("call_id") or "")
        items = _call_items(call)
        tool_calls[tool] += 1
        tool_items[tool] += len(items)

        for item in items:
            for field in _ASSET_FIELDS:
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    asset_urls.add(value.strip())

            if tool == "add_captions":
                font = str(_effective(call, item, "font") or "").strip()
                color = str(_effective(call, item, "text_color") or "").strip().upper()
                if font:
                    fonts[font] += 1
                if color:
                    text_colors[color] += 1
                for field in ("in_animation", "out_animation", "loop_animation"):
                    animation = str(_effective(call, item, field) or "").strip()
                    if animation:
                        text_animations[animation] += 1
                if call_id in _TITLE_CALL_IDS and font != "出云龙":
                    title_font_mismatches.append({"call_id": call_id, "font": font or "<missing>"})
                if call_id == "main_captions":
                    main_caption_styles.append({"font": font, "text_color": color})

            elif tool in {"add_images", "add_videos"}:
                for field in ("in_animation", "out_animation", "group_animation"):
                    animation = str(_effective(call, item, field) or "").strip()
                    if animation:
                        image_animations[animation] += 1
            elif tool == "add_keyframes":
                prop = str(item.get("property") or item.get("property_type") or "").strip()
                if prop:
                    keyframe_properties[prop] += 1
            elif tool == "add_effects":
                title = str(item.get("effect_title") or item.get("title") or item.get("name") or "").strip()
                if title:
                    effect_titles[title] += 1

    checks: list[dict[str, Any]] = []

    def check(check_id: str, label: str, passed: bool, detail: str, *, required: bool = True) -> None:
        checks.append(
            {
                "id": check_id,
                "label": label,
                "result": "passed" if passed else ("failed" if required else "warning"),
                "detail": detail,
            }
        )

    draft_id = str(import_report.get("draft_id") or "").strip()
    draft_dir_text = str(import_report.get("draft_dir") or "").strip()
    draft_dir = Path(draft_dir_text) if draft_dir_text else None
    check(
        "local_draft",
        "本地草稿已落盘",
        bool(draft_id and draft_dir and draft_dir.is_dir()),
        f"draft_id={draft_id or '<missing>'}; dir={draft_dir_text or '<missing>'}",
    )

    meta = key.get("meta") or {}
    unresolved = sorted({str(value) for value in _as_list(meta.get("unresolved_segment_ids")) if str(value)})
    check(
        "segment_refs",
        "关键帧片段引用可解析",
        not unresolved,
        "无未解析片段" if not unresolved else f"未解析 {len(unresolved)} 个片段",
    )
    check("audio", "存在音频", tool_items["add_audios"] > 0, f"{tool_items['add_audios']} 条")
    check(
        "images",
        "存在图片或视频",
        tool_items["add_images"] + tool_items["add_videos"] > 0,
        f"图片 {tool_items['add_images']} 条，视频 {tool_items['add_videos']} 条",
    )
    check("captions", "存在字幕", tool_items["add_captions"] > 0, f"{tool_items['add_captions']} 条")

    broken_fonts = sorted(font for font in fonts if "?" in font or "\ufffd" in font)
    check(
        "font_integrity",
        "字体名称完整",
        not broken_fonts,
        "未发现乱码字体" if not broken_fonts else "乱码字体：" + "、".join(broken_fonts),
    )

    if profile == "god":
        check(
            "god_title_font",
            "神模板标题字体为出云龙",
            bool(fonts.get("出云龙")) and not title_font_mismatches,
            "标题字体均为出云龙" if not title_font_mismatches else f"{len(title_font_mismatches)} 个标题轨道字体不符",
        )
        main_style_ok = bool(main_caption_styles) and all(
            style["font"] == "江湖体" and style["text_color"] == "#FFDE00"
            for style in main_caption_styles
        )
        check(
            "god_main_caption_style",
            "正文字体与颜色符合模板",
            main_style_ok,
            "江湖体 / #FFDE00" if main_style_ok else "应为江湖体 / #FFDE00",
        )
        expected_text_animations = {"滚入", "放大"}
        missing_text_animations = sorted(expected_text_animations - set(text_animations))
        check(
            "god_text_animations",
            "标题文字动画完整",
            not missing_text_animations,
            "包含滚入、放大" if not missing_text_animations else "缺少：" + "、".join(missing_text_animations),
        )

    check(
        "image_animations",
        "图片动画已记录",
        bool(image_animations),
        f"{sum(image_animations.values())} 条" if image_animations else "未记录图片动画",
        required=False,
    )
    keyframe_names = set(keyframe_properties)
    camera_ok = {
        "KFTypePositionX",
        "KFTypePositionY",
    }.issubset(keyframe_names) and bool(keyframe_names & _UNIFORM_SCALE_PROPERTIES)
    check(
        "camera_keyframes",
        "图片滑动关键帧完整",
        camera_ok,
        f"{sum(keyframe_properties.values())} 个关键帧" if camera_ok else "应包含 X、Y、统一缩放关键帧",
        required=False,
    )
    check(
        "effects",
        "画面特效已记录",
        bool(effect_titles),
        f"{sum(effect_titles.values())} 条" if effect_titles else "未记录画面特效",
        required=False,
    )

    import_warnings = [str(value) for value in _as_list(import_report.get("warnings"))]
    check(
        "import_warnings",
        "本地写入无警告",
        not import_warnings,
        "无写入警告" if not import_warnings else f"{len(import_warnings)} 条写入警告",
        required=False,
    )

    result_counts = Counter(item["result"] for item in checks)
    status = "failed" if result_counts["failed"] else ("warning" if result_counts["warning"] else "passed")
    status_text = {"passed": "验收通过", "warning": "验收有警告", "failed": "验收失败"}[status]
    return {
        "report_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "profile": profile,
        "status": status,
        "status_text": status_text,
        "draft_id": draft_id,
        "summary": {
            "call_count": len(calls),
            "asset_url_count": len(asset_urls),
            "tool_call_counts": _counter_dict(tool_calls),
            "tool_item_counts": _counter_dict(tool_items),
            "passed_checks": result_counts["passed"],
            "warning_checks": result_counts["warning"],
            "failed_checks": result_counts["failed"],
        },
        "details": {
            "fonts": _counter_dict(fonts),
            "text_colors": _counter_dict(text_colors),
            "text_animations": _counter_dict(text_animations),
            "image_animations": _counter_dict(image_animations),
            "keyframe_properties": _counter_dict(keyframe_properties),
            "effects": _counter_dict(effect_titles),
            "unresolved_segment_ids": unresolved,
            "import_warnings": import_warnings,
        },
        "checks": checks,
    }
