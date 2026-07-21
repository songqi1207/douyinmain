#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「key 数据包 → 本地剪映草稿」导入器。

key 由 Coze 工作流汇总输出（音频/图片/字幕/关键帧/特效的有序调用序列），
本模块按序调用 utils.jianying_drafts 里的 append_* 函数在本地生成完整草稿。
四阶段：validate → prefetch → execute → report。字段级 schema 见 docs/draft_key_schema.md。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from utils.jianying_drafts import (
    _draft_root,
    append_audios,
    append_captions,
    append_effects,
    append_images,
    append_keyframes,
    create_draft,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _PROJECT_ROOT / "temp" / "draft_key_cache"
_REGISTRY_PATH = _PROJECT_ROOT / "temp" / "draft_key_imports.json"
_RENDER_KEYS_DIR = _PROJECT_ROOT / "temp" / "draft_render_keys"

_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_TIMEOUT = 60

_SEGMENT_TOOLS = {"add_audios", "add_images", "add_captions", "add_effects"}
_KNOWN_TOOLS = _SEGMENT_TOOLS | {"add_keyframes"}

_KEYFRAME_PROPERTIES = {
    "UNIFORM_SCALE",
    "KFTypeUniformScale",
    "KFTypePositionX",
    "KFTypePositionY",
    "KFTypeRotation",
    "KFTypeScaleX",
    "KFTypeScaleY",
    "KFTypeAlpha",
    "KFTypeVolume",
    "KFTypeSaturation",
    "KFTypeContrast",
    "KFTypeBrightness",
}

# 各工具的素材 URL 字段与列表字段名（含 Coze 侧常见别名）
_LIST_FIELDS = {
    "add_audios": ("audio_infos", "infos", "audios"),
    "add_images": ("image_infos", "infos", "imgs", "images"),
    "add_captions": ("captions", "infos", "texts"),
    "add_keyframes": ("keyframes", "infos"),
    "add_effects": ("effect_infos", "infos", "effects"),
}
_ASSET_FIELDS = ("audio_url", "image_url", "img", "url", "path", "file_path")
_IMAGE_STYLE_FIELDS = (
    "alpha",
    "scale_x",
    "scale_y",
    "transform_x",
    "transform_y",
    "in_animation",
    "in_animation_duration",
    "out_animation",
    "out_animation_duration",
)

# 剪映 clip.transform / 位置关键帧是归一化坐标；剪映小助手传的是剪映 UI 显示的像素值。
# 换算规则与 pyJianYingDraft 一致：归一化值 = 显示值 / 整边长（x 除以宽、y 除以高）。
# |值| > 阈值判定为像素。真机校准点：若位置幅度整体差一倍，把除数改成 边长/2。
_PIXEL_THRESHOLD = 3.0


class KeyValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class AssetDownloadError(RuntimeError):
    def __init__(self, failed: dict[str, str]):
        super().__init__(f"{len(failed)} asset(s) failed to download")
        self.failed = failed


def _as_list(value: Any) -> list:
    """Coze 代码节点常把列表输出成 JSON 字符串，这里统一还原。"""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _call_items(call: dict[str, Any]) -> list[dict[str, Any]]:
    params = call.get("params") or {}
    for field in _LIST_FIELDS.get(call.get("tool", ""), ()):
        if field in params:
            return [item for item in _as_list(params[field]) if isinstance(item, dict)]
    return []


def _fingerprint(key: dict[str, Any]) -> str:
    run_id = str(((key.get("meta") or {}).get("run_id")) or "").strip()
    if run_id:
        return run_id
    canonical = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_registry() -> dict[str, Any]:
    if _REGISTRY_PATH.exists():
        try:
            payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {}


def _save_registry(registry: dict[str, Any]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")


def _save_render_key(draft_id: str, key: dict[str, Any]) -> Path:
    """Persist the semantic source used by the FFmpeg renderer.

    JianYing's draft JSON contains resource IDs and flattened track data, while
    draft_key keeps the portable intent (asset URL, caption style, keyframes,
    and effect names).  Keeping this sidecar makes ``draft_id -> MP4`` possible
    without reverse engineering the generated JianYing folder again.
    """
    _RENDER_KEYS_DIR.mkdir(parents=True, exist_ok=True)
    target = _RENDER_KEYS_DIR / f"{draft_id}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def _validate_key(key: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(key, dict):
        return ["key 必须是 JSON 对象"]

    kind = key.get("kind")
    if kind not in (None, "", "jianying_draft_key"):
        errors.append(f"kind 不识别: {kind}")

    calls = key.get("calls")
    if not isinstance(calls, list) or not calls:
        errors.append("calls 必须是非空数组")
        return errors

    seen_ids: set[str] = set()
    segment_call_ids: set[str] = set()
    for index, call in enumerate(calls):
        label = f"calls[{index}]"
        if not isinstance(call, dict):
            errors.append(f"{label} 必须是对象")
            continue
        tool = str(call.get("tool") or "").strip()
        if tool not in _KNOWN_TOOLS:
            errors.append(f"{label} tool 不支持: {tool!r}（可选: {sorted(_KNOWN_TOOLS)}）")
            continue
        # 与 execute 阶段保持同一套缺省 call_id，segment_ref 才能对得上
        call_id = str(call.get("call_id") or f"call_{index:02d}").strip()
        if call_id in seen_ids:
            errors.append(f"{label} call_id 重复: {call_id}")
        seen_ids.add(call_id)

        items = _call_items(call)
        if not items:
            errors.append(f"{label} ({tool}) 没有可用条目（检查 params 列表字段/JSON 字符串格式）")

        if tool == "add_keyframes":
            for item_index, item in enumerate(items):
                item_label = f"{label}.keyframes[{item_index}]"
                prop = str(item.get("property") or item.get("property_type") or "").strip()
                if prop and prop not in _KEYFRAME_PROPERTIES:
                    errors.append(f"{item_label} property 不识别: {prop}")
                ref = item.get("segment_ref")
                if ref is None:
                    if not str(item.get("segment_id") or "").strip():
                        errors.append(f"{item_label} 缺少 segment_ref 或 segment_id")
                    continue
                if not isinstance(ref, dict):
                    errors.append(f"{item_label} segment_ref 必须是对象 {{call_id,index}}")
                    continue
                ref_id = str(ref.get("call_id") or "").strip()
                if ref_id not in segment_call_ids:
                    errors.append(f"{item_label} segment_ref.call_id 未指向前面的片段调用: {ref_id!r}")
                try:
                    if int(ref.get("index", 0)) < 0:
                        errors.append(f"{item_label} segment_ref.index 不能为负")
                except (TypeError, ValueError):
                    errors.append(f"{item_label} segment_ref.index 必须是整数")
        else:
            segment_call_ids.add(call_id)

    return errors


def _collect_asset_urls(key: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for call in key.get("calls", []):
        if not isinstance(call, dict) or call.get("tool") not in ("add_audios", "add_images"):
            continue
        for item in _call_items(call):
            for field in _ASSET_FIELDS:
                target = str(item.get(field) or "").strip()
                if target:
                    if urlparse(target).scheme in ("http", "https") and target not in urls:
                        urls.append(target)
                    break
    return urls


def _cache_path(url: str) -> Path:
    suffix = Path(urlparse(url).path).suffix[:8]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return _CACHE_DIR / f"{digest}{suffix}"


def _prefetch_assets(urls: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    asset_map: dict[str, str] = {}
    failed: dict[str, str] = {}
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for url in urls:
        target = _cache_path(url)
        if target.exists() and target.stat().st_size > 0:
            asset_map[url] = str(target)
            continue
        last_error = ""
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            try:
                response = requests.get(url, timeout=_DOWNLOAD_TIMEOUT)
                response.raise_for_status()
                target.write_bytes(response.content)
                asset_map[url] = str(target)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                time.sleep(min(2**attempt, 4))
        else:
            failed[url] = last_error
    return asset_map, failed


def _localize_items(items: list[dict[str, Any]], asset_map: dict[str, str]) -> list[dict[str, Any]]:
    localized = []
    for item in items:
        copied = dict(item)
        for field in _ASSET_FIELDS:
            target = str(copied.get(field) or "").strip()
            if target:
                if target in asset_map:
                    copied[field] = asset_map[target]
                break
        localized.append(copied)
    return localized


def _merge_global_image_style(
    items: list[dict[str, Any]], params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Apply add_images node-level styling while preserving item overrides."""
    global_style = {
        key: params[key]
        for key in _IMAGE_STYLE_FIELDS
        if params.get(key) not in (None, "")
    }
    if not global_style:
        return items
    return [{**global_style, **item} for item in items]


def _normalize_transform(value: Any, canvas_dim: int) -> Any:
    """像素坐标 → 剪映归一化坐标（1.0 = 半边长）；已归一化的值原样通过。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if abs(number) <= _PIXEL_THRESHOLD or canvas_dim <= 0:
        return number
    return round(number / float(canvas_dim), 6)


def _normalize_item_transforms(items: list[dict[str, Any]], width: int, height: int) -> None:
    for item in items:
        if "transform_x" in item:
            item["transform_x"] = _normalize_transform(item["transform_x"], width)
        if "transform_y" in item:
            item["transform_y"] = _normalize_transform(item["transform_y"], height)


def import_draft_key(key: dict[str, Any], *, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    errors = _validate_key(key)
    if errors:
        raise KeyValidationError(errors)

    asset_urls = _collect_asset_urls(key)
    fingerprint = _fingerprint(key)

    if dry_run:
        return {
            "dry_run": True,
            "fingerprint": fingerprint,
            "calls": [
                {"call_id": str(call.get("call_id") or f"call_{index:02d}"), "tool": call.get("tool"), "items": len(_call_items(call))}
                for index, call in enumerate(key["calls"])
            ],
            "asset_urls": asset_urls,
            "message": "ok",
        }

    registry = _load_registry()
    existing = registry.get(fingerprint)
    if existing and not force:
        draft_dir = Path(str(existing.get("draft_dir") or ""))
        if draft_dir.exists():
            render_key_path = _save_render_key(str(existing.get("draft_id") or ""), key)
            existing["render_key_path"] = str(render_key_path)
            registry[fingerprint] = existing
            _save_registry(registry)
            return {**existing, "already_imported": True, "message": "ok"}
        registry.pop(fingerprint, None)

    if existing and force:
        old_dir = Path(str(existing.get("draft_dir") or ""))
        if old_dir.exists():
            import shutil

            shutil.rmtree(old_dir, ignore_errors=True)
        _unregister_root_meta(str(existing.get("draft_id") or ""))
        registry.pop(fingerprint, None)

    asset_map, failed = _prefetch_assets(asset_urls)
    if failed:
        raise AssetDownloadError(failed)

    draft_cfg = key.get("draft") or {}
    width = int(float(draft_cfg.get("width") or 1920))
    height = int(float(draft_cfg.get("height") or 1080))
    meta = key.get("meta") or {}
    name = str(draft_cfg.get("name") or meta.get("title") or "draft_key")

    created = create_draft(width, height, name)
    draft_id = created["draft_id"]

    call_results: dict[str, dict[str, Any]] = {}
    report_calls: list[dict[str, Any]] = []
    warnings: list[str] = []
    type_counters = {"add_audios": 0, "add_images": 0, "add_captions": 0, "add_effects": 0}
    render_base = {"add_audios": 11000, "add_images": 14000, "add_captions": 15000, "add_effects": 16000}
    track_prefix = {"add_audios": "audio", "add_images": "video", "add_captions": "text", "add_effects": "effect"}

    for index, call in enumerate(key["calls"]):
        tool = call["tool"]
        call_id = str(call.get("call_id") or f"call_{index:02d}").strip()
        params = call.get("params") or {}
        items = _localize_items(_call_items(call), asset_map)

        result: dict[str, Any]
        if tool == "add_keyframes":
            keyframes = []
            for item in items:
                resolved = dict(item)
                ref = resolved.pop("segment_ref", None)
                if isinstance(ref, dict):
                    ref_result = call_results.get(str(ref.get("call_id") or "").strip(), {})
                    segment_infos = ref_result.get("segment_infos") or []
                    ref_index = int(ref.get("index", 0))
                    if ref_index >= len(segment_infos):
                        warnings.append(f"{call_id}: segment_ref index {ref_index} 超出 {ref.get('call_id')} 的片段数量，已跳过")
                        continue
                    resolved["segment_id"] = segment_infos[ref_index]["id"]
                keyframes.append(resolved)
            result = append_keyframes(draft_id, keyframes)
        else:
            counter = type_counters[tool]
            type_counters[tool] += 1
            track_name = str(call.get("track_name") or "").strip() or f"{track_prefix[tool]}_{counter:02d}_{call_id}"
            render_index = call.get("render_index")
            render_index = int(render_index) if render_index is not None else render_base[tool] + counter

            if tool == "add_audios":
                result = append_audios(draft_id, items, track_name=track_name, render_index=render_index)
            elif tool == "add_images":
                # Mihe permits clip styling either on every image item or as
                # top-level add_images parameters.  The recorder preserves the
                # latter, so merge them before writing JianYing segments.
                items = _merge_global_image_style(items, params)
                _normalize_item_transforms(items, width, height)
                result = append_images(draft_id, items, params.get("alpha"), track_name=track_name, render_index=render_index)
            elif tool == "add_captions":
                style_keys = (
                    "alpha",
                    "alignment",
                    "border_color",
                    "font",
                    "font_size",
                    "letter_spacing",
                    "line_spacing",
                    "scale_x",
                    "scale_y",
                    "style_text",
                    "text_color",
                    "transform_x",
                    "transform_y",
                )
                style = {k: params[k] for k in style_keys if params.get(k) not in (None, "")}
                if "transform_x" in style:
                    style["transform_x"] = _normalize_transform(style["transform_x"], width)
                if "transform_y" in style:
                    style["transform_y"] = _normalize_transform(style["transform_y"], height)
                _normalize_item_transforms(items, width, height)
                result = append_captions(draft_id, items, track_name=track_name, render_index=render_index, **style)
            else:  # add_effects
                result = append_effects(draft_id, items, track_name=track_name, render_index=render_index)

        for warning in result.get("warnings") or []:
            warnings.append(f"{call_id}: {warning}")
        call_results[call_id] = result
        report_calls.append(
            {
                "call_id": call_id,
                "tool": tool,
                "segment_ids": result.get("segment_ids", []),
                "track_id": result.get("track_id", ""),
                "applied": result.get("applied"),
            }
        )

    render_key_path = _save_render_key(draft_id, key)
    report = {
        "draft_id": draft_id,
        "draft_name": created["draft_name"],
        "draft_dir": created["draft_dir"],
        "fingerprint": fingerprint,
        "already_imported": False,
        "calls": report_calls,
        "warnings": warnings,
        "render_key_path": str(render_key_path),
        "message": "ok",
    }
    registry[fingerprint] = {
        "draft_id": draft_id,
        "draft_name": created["draft_name"],
        "draft_dir": created["draft_dir"],
        "fingerprint": fingerprint,
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "render_key_path": str(render_key_path),
    }
    _save_registry(registry)
    return report


def _unregister_root_meta(draft_id: str) -> None:
    if not draft_id:
        return
    root_meta_path = _draft_root() / "root_meta_info.json"
    if not root_meta_path.exists():
        return
    try:
        payload = json.loads(root_meta_path.read_text(encoding="utf-8"))
        entries = payload.get("all_draft_store")
        if isinstance(entries, list):
            payload["all_draft_store"] = [item for item in entries if str(item.get("draft_id")) != draft_id]
            root_meta_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except Exception:
        pass
