#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local JianYing/CapCut draft creation helpers."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from utils.audio_probe import probe_audio_duration

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is optional at runtime
    Image = None


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FALLBACK_DRAFT_ROOT = _PROJECT_ROOT / "temp" / "jianying_drafts"
_TRACK_RANK = {
    "video": 0,
    "audio": 1,
    "sticker": 2,
    "effect": 3,
    "filter": 4,
    "text": 5,
}
_REMOTE_TIMEOUT = 60


def _draft_root() -> Path:
    configured = os.getenv("JIANYING_DRAFT_ROOT", "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        configured_path.mkdir(parents=True, exist_ok=True)
        return configured_path

    candidates = []

    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        local_root = Path(local_appdata)
        candidates.extend(
            [
                local_root / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
                local_root / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate

    _FALLBACK_DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
    return _FALLBACK_DRAFT_ROOT


def _generate_id() -> str:
    return str(uuid.uuid4()).upper()


def _timestamp_us() -> int:
    return int(time.time() * 1_000_000)


def _safe_name(value: str, fallback: str = "coze_draft") -> str:
    raw = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "-_ ")
    raw = raw.strip().replace(" ", "_")
    return raw[:80] or fallback


def _ensure_track(draft: dict[str, Any], track_type: str, track_name: str) -> dict[str, Any]:
    for track in draft["tracks"]:
        if track.get("type") == track_type and track.get("name") == track_name:
            return track

    track = {
        "id": _generate_id(),
        "type": track_type,
        "name": track_name,
        "attribute": 0,
        "flag": 0,
        "segments": [],
    }
    draft["tracks"].append(track)
    return track


def _sort_tracks(draft: dict[str, Any]) -> None:
    indexed_tracks = list(enumerate(draft.get("tracks", [])))
    indexed_tracks.sort(key=lambda pair: (_TRACK_RANK.get(str(pair[1].get("type", "")), 99), pair[0]))
    draft["tracks"] = [track for _, track in indexed_tracks]


def _duration_to_us(value: Any) -> int:
    if value in (None, "", False):
        return 0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if abs(number) < 10_000:
        return max(0, int(round(number * 1_000_000)))
    return max(0, int(round(number)))


def _target_end_us(item: dict[str, Any]) -> int:
    end = _duration_to_us(item.get("end"))
    if end > 0:
        return end
    start = _duration_to_us(item.get("start"))
    duration = _duration_to_us(item.get("duration"))
    return start + duration


def _update_draft_duration(bundle: dict[str, Any]) -> None:
    max_end = 0
    for track in bundle["content"].get("tracks", []):
        for segment in track.get("segments", []):
            target = segment.get("target_timerange") or {}
            start = int(target.get("start") or 0)
            duration = int(target.get("duration") or 0)
            max_end = max(max_end, start + duration)
    bundle["content"]["duration"] = max_end
    bundle["meta"]["tm_duration"] = max_end
    bundle["meta"]["draft_timeline_materials_size_"] = sum(
        len(track.get("segments", [])) for track in bundle["content"].get("tracks", [])
    )


def _ratio_from_size(width: int, height: int) -> str:
    if not width or not height:
        return "original"
    if width == height:
        return "1:1"
    if abs(width * 9 - height * 16) <= max(width, height) // 20:
        return "16:9"
    if abs(width * 16 - height * 9) <= max(width, height) // 20:
        return "9:16"
    return "original"


def _new_content_template(width: int, height: int, name: str, draft_id: str) -> dict[str, Any]:
    return {
        "id": draft_id,
        "name": name,
        "duration": 0,
        "create_time": 0,
        "update_time": 0,
        "fps": 30.0,
        "version": 360000,
        "free_render_index_mode_on": False,
        "render_index_track_mode_on": False,
        "source": "default",
        "new_version": "103.0.0",
        "canvas_config": {
            "width": width,
            "height": height,
            "ratio": _ratio_from_size(width, height),
        },
        "platform": {
            "app_id": 3704,
            "app_source": "lv",
            "app_version": "5.5.0",
            "device_id": "",
            "hard_disk_id": "",
            "mac_address": "",
            "os": "windows",
            "os_version": "",
        },
        "last_modified_platform": {
            "app_id": 3704,
            "app_source": "lv",
            "app_version": "5.5.0",
            "device_id": "",
            "hard_disk_id": "",
            "mac_address": "",
            "os": "windows",
            "os_version": "",
        },
        "color_space": 0,
        "cover": None,
        "extra_info": {"created_via": "douyinmain_local_tools"},
        "group_container": None,
        "keyframe_graph_list": [],
        "keyframes": {
            "adjusts": [],
            "audios": [],
            "effects": [],
            "filters": [],
            "handwrites": [],
            "stickers": [],
            "texts": [],
            "videos": [],
        },
        "materials": {
            "ai_translates": [],
            "audio_balances": [],
            "audio_effects": [],
            "audio_fades": [],
            "audio_track_indexes": [],
            "audios": [],
            "beats": [],
            "canvases": [],
            "chromas": [],
            "color_curves": [],
            "digital_humans": [],
            "drafts": [],
            "effects": [],
            "flowers": [],
            "green_screens": [],
            "handwrites": [],
            "hsl": [],
            "images": [],
            "log_color_wheels": [],
            "loudnesses": [],
            "manual_deformations": [],
            "masks": [],
            "material_animations": [],
            "material_colors": [],
            "placeholders": [],
            "plugin_effects": [],
            "primary_color_wheels": [],
            "realtime_denoises": [],
            "shapes": [],
            "smart_crops": [],
            "smart_relights": [],
            "sound_channel_mappings": [],
            "speeds": [],
            "stickers": [],
            "tail_leaders": [],
            "text_templates": [],
            "texts": [],
            "time_marks": [],
            "transitions": [],
            "video_effects": [],
            "video_trackings": [],
            "videos": [],
            "vocal_beautifys": [],
            "vocal_separations": [],
        },
        "mutable_config": None,
        "relationships": [],
        "retouch_cover": None,
        "static_cover_image_path": "",
        "time_marks": None,
        "tracks": [],
    }


def _new_meta_template(name: str, draft_id: str, draft_dir: Path, draft_root: Path) -> dict[str, Any]:
    now_us = _timestamp_us()
    return {
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_materials": [],
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "draft_cover.jpg",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "",
            "draft_enterprise_id": "",
            "draft_enterprise_name": "",
            "enterprise_material": [],
        },
        "draft_fold_path": str(draft_dir),
        "draft_id": draft_id,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_materials": [
            {"type": 0, "value": []},
            {"type": 1, "value": []},
            {"type": 2, "value": []},
            {"type": 3, "value": []},
            {"type": 6, "value": []},
            {"type": 7, "value": []},
            {"type": 8, "value": []},
        ],
        "draft_materials_copied_info": [],
        "draft_name": name,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": str(draft_root),
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": 0,
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": 0,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _write_bundle(bundle: dict[str, Any]) -> None:
    draft_dir = bundle["draft_dir"]
    content = bundle["content"]
    meta = bundle["meta"]

    _sort_tracks(content)
    _update_draft_duration(bundle)
    now_us = _timestamp_us()
    content["update_time"] = now_us
    meta["tm_draft_modified"] = now_us

    _write_json(draft_dir / "draft_content.json", content)
    _write_json(draft_dir / "draft_info.json", content)
    _write_json(draft_dir / "template-2.tmp", {"draft_content": json.dumps(content, ensure_ascii=False, separators=(",", ":"))})
    _write_json(draft_dir / "draft_meta_info.json", meta)
    _register_root_meta(meta, draft_dir / "draft_content.json")


def _register_root_meta(meta: dict[str, Any], content_path: Path) -> None:
    root_path = Path(meta["draft_root_path"])
    root_path.mkdir(parents=True, exist_ok=True)
    root_meta_path = root_path / "root_meta_info.json"
    if root_meta_path.exists():
        try:
            root_payload = json.loads(root_meta_path.read_text(encoding="utf-8"))
        except Exception:
            root_payload = {}
    else:
        root_payload = {}

    entries = root_payload.get("all_draft_store")
    if not isinstance(entries, list):
        entries = []

    entry = {
        "draft_cover": meta.get("draft_cover", "draft_cover.jpg"),
        "draft_fold_path": meta["draft_fold_path"],
        "draft_id": meta["draft_id"],
        "draft_is_ai_shorts": False,
        "draft_is_invisible": False,
        "draft_json_file": str(content_path),
        "draft_name": meta["draft_name"],
        "draft_new_version": meta.get("draft_new_version", ""),
        "draft_root_path": meta["draft_root_path"],
        "draft_timeline_materials_size": meta.get("draft_timeline_materials_size_", 0),
        "tm_draft_create": meta["tm_draft_create"],
        "tm_draft_modified": meta["tm_draft_modified"],
        "tm_draft_removed": 0,
        "tm_duration": meta.get("tm_duration", 0),
    }

    entries = [item for item in entries if str(item.get("draft_id", "")) != meta["draft_id"]]
    entries.append(entry)
    root_payload["all_draft_store"] = entries
    _write_json(root_meta_path, root_payload)


def _load_bundle(draft_id: str) -> dict[str, Any]:
    target_id = str(draft_id or "").strip()
    if not target_id:
        raise ValueError("missing draft_id")

    draft_dir = _draft_root() / target_id
    content_path = draft_dir / "draft_content.json"
    meta_path = draft_dir / "draft_meta_info.json"
    if not content_path.exists() or not meta_path.exists():
        raise FileNotFoundError(f"draft not found: {target_id}")

    return {
        "draft_dir": draft_dir,
        "content": json.loads(content_path.read_text(encoding="utf-8")),
        "meta": json.loads(meta_path.read_text(encoding="utf-8")),
    }


def create_draft(width: Any = 1920, height: Any = 1080, name: str = "", user_id: Any = None) -> dict[str, Any]:
    try:
        width_int = max(1, int(float(width or 1920)))
        height_int = max(1, int(float(height or 1080)))
    except (TypeError, ValueError):
        raise ValueError("width and height must be numeric")

    draft_root = _draft_root()
    draft_id = _generate_id()
    suffix = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    draft_name = _safe_name(name, fallback=f"coze_draft_{suffix}")
    draft_dir = draft_root / draft_id
    draft_dir.mkdir(parents=True, exist_ok=False)
    (draft_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True)
    (draft_dir / "assets" / "video").mkdir(parents=True, exist_ok=True)

    bundle = {
        "draft_dir": draft_dir,
        "content": _new_content_template(width_int, height_int, draft_name, draft_id),
        "meta": _new_meta_template(draft_name, draft_id, draft_dir, draft_root),
    }
    if user_id not in (None, ""):
        try:
            bundle["meta"]["user_id"] = int(float(user_id))
        except (TypeError, ValueError):
            bundle["meta"]["user_id"] = str(user_id)

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "draft_name": draft_name,
        "draft_dir": str(draft_dir),
        "width": width_int,
        "height": height_int,
        "ratio": bundle["content"]["canvas_config"]["ratio"],
        "message": "ok",
    }


def _guess_remote_suffix(url: str, content_type: str = "") -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix
    if suffix:
        return suffix
    ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    return ext or ""


def _materialize_asset(target: str, draft_dir: Path, kind: str, fallback_ext: str = "") -> Path:
    raw = str(target or "").strip()
    if not raw:
        raise ValueError("missing asset target")

    asset_dir = draft_dir / "assets" / kind
    asset_dir.mkdir(parents=True, exist_ok=True)

    scheme = (urlparse(raw).scheme or "").lower()
    if scheme in {"http", "https"}:
        response = requests.get(raw, timeout=_REMOTE_TIMEOUT)
        response.raise_for_status()
        suffix = _guess_remote_suffix(raw, response.headers.get("Content-Type", "")) or fallback_ext
        asset_path = asset_dir / f"{_generate_id()}{suffix}"
        asset_path.write_bytes(response.content)
        return asset_path

    source = Path(raw).expanduser()
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()
    if not source.exists():
        raise FileNotFoundError(f"asset file not found: {source}")
    suffix = source.suffix or fallback_ext
    asset_path = asset_dir / f"{_generate_id()}{suffix}"
    shutil.copy2(source, asset_path)
    return asset_path


def _infer_image_size(path: Path) -> tuple[int, int]:
    if Image is None:
        return 1920, 1080
    with Image.open(path) as image:
        return int(image.width or 1920), int(image.height or 1080)


def _build_audio_material(path: Path, duration_us: int) -> dict[str, Any]:
    return {
        "id": _generate_id(),
        "app_id": 0,
        "category_id": "",
        "category_name": "local",
        "check_flag": 1,
        "duration": duration_us,
        "effect_id": "",
        "formula_id": "",
        "intensifies_path": "",
        "local_material_id": "",
        "music_id": _generate_id(),
        "name": path.name,
        "path": str(path),
        "request_id": "",
        "resource_id": "",
        "source_platform": 0,
        "team_id": "",
        "text_id": "",
        "tone_category_id": "",
        "tone_category_name": "",
        "tone_effect_id": "",
        "tone_effect_name": "",
        "tone_speaker": "",
        "tone_type": "",
        "type": "extract_music",
        "video_id": "",
        "wave_points": [],
    }


def _build_video_material(path: Path, duration_us: int, width: int, height: int) -> dict[str, Any]:
    return {
        "id": _generate_id(),
        "audio_fade": None,
        "category_id": "",
        "category_name": "local",
        "check_flag": 7,
        "crop": {
            "lower_left_x": 0.0,
            "lower_left_y": 1.0,
            "lower_right_x": 1.0,
            "lower_right_y": 1.0,
            "upper_left_x": 0.0,
            "upper_left_y": 0.0,
            "upper_right_x": 1.0,
            "upper_right_y": 0.0,
        },
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "duration": duration_us,
        "extra_type_option": 0,
        "formula_id": "",
        "freeze": None,
        "has_audio": False,
        "height": height,
        "intensifies_audio_path": "",
        "intensifies_path": "",
        "is_unified_beauty_mode": False,
        "local_id": "",
        "local_material_id": "",
        "material_id": "",
        "material_name": path.name,
        "material_url": "",
        "media_path": "",
        "object_locked": None,
        "path": str(path),
        "picture_from": "none",
        "request_id": "",
        "reverse_path": "",
        "source_platform": 0,
        "team_id": "",
        "type": "photo",
        "video_algorithm": {
            "algorithms": [],
            "deflicker": None,
            "motion_blur_config": None,
            "noise_reduction": None,
            "path": "",
            "time_range": None,
        },
        "width": width,
    }


def _build_text_material(text: str, font_size: float, text_color: str, border_color: str, line_spacing: float, alignment: int, font_name: str) -> dict[str, Any]:
    utf16_bytes = len(text.encode("utf-16le"))
    style_payload = {
        "styles": [
            {
                "range": [0, utf16_bytes],
                "size": font_size,
                "bold": False,
                "italic": False,
                "underline": False,
                "fill": {
                    "alpha": 1,
                    "content": {
                        "render_type": "solid",
                        "solid": {"alpha": 1, "color": text_color},
                    },
                },
            }
        ],
        "text": text,
    }
    return {
        "id": _generate_id(),
        "type": "text",
        "content": json.dumps(style_payload, ensure_ascii=False, separators=(",", ":")),
        "alignment": alignment,
        "font_size": font_size,
        "text_color": text_color,
        "typesetting": 0,
        "letter_spacing": 0,
        "line_spacing": line_spacing,
        "line_feed": 1,
        "line_max_width": 0.82,
        "force_apply_line_max_width": False,
        "check_flag": 7,
        "fixed_width": -1,
        "fixed_height": -1,
        "border_color": border_color,
        "font_name": font_name,
    }


def _base_segment(material_id: str, start_us: int, duration_us: int, render_index: int, clip_override: dict[str, Any] | None = None) -> dict[str, Any]:
    clip = {
        "alpha": 1.0,
        "flip": {"horizontal": False, "vertical": False},
        "rotation": 0.0,
        "scale": {"x": 1.0, "y": 1.0},
        "transform": {"x": 0.0, "y": 0.0},
    }
    if clip_override:
        for key, value in clip_override.items():
            if key in {"alpha", "rotation"}:
                clip[key] = value
            elif key == "scale":
                clip["scale"].update(value or {})
            elif key == "transform":
                clip["transform"].update(value or {})

    return {
        "id": _generate_id(),
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "source_timerange": {"start": 0, "duration": duration_us},
        "speed": 1.0,
        "volume": 1.0,
        "visible": True,
        "clip": clip,
        "extra_material_refs": [],
        "common_keyframes": [],
        "keyframe_refs": [],
        "render_index": render_index,
        "track_render_index": 0,
        "track_attribute": 0,
        "reverse": False,
    }


def append_audios(draft_id: str, audio_infos: list[dict[str, Any]]) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "audio", "audio")
    items = []

    for info in audio_infos or []:
        if not isinstance(info, dict):
            continue
        target = info.get("audio_url") or info.get("url") or info.get("path") or info.get("file_path")
        if not target:
            continue
        start_us = _duration_to_us(info.get("start"))
        end_us = _target_end_us(info)
        if end_us <= start_us:
            duration_us = _duration_to_us(info.get("duration"))
            if duration_us <= 0:
                duration_us = _duration_to_us(probe_audio_duration(str(target)))
            end_us = start_us + duration_us
        duration_us = max(0, end_us - start_us)
        asset_path = _materialize_asset(str(target), bundle["draft_dir"], "audio", ".mp3")
        material = _build_audio_material(asset_path, duration_us)
        draft["materials"]["audios"].append(material)

        segment = _base_segment(material["id"], start_us, duration_us, 11000)
        segment["volume"] = float(info.get("volume", 1) or 1)
        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
    }


def append_images(draft_id: str, image_infos: list[dict[str, Any]], alpha: Any = None) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "video", "video")
    items = []

    for info in image_infos or []:
        if not isinstance(info, dict):
            continue
        target = info.get("image_url") or info.get("img") or info.get("url") or info.get("path") or info.get("file_path")
        if not target:
            continue
        start_us = _duration_to_us(info.get("start"))
        end_us = _target_end_us(info)
        if end_us <= start_us:
            duration_us = _duration_to_us(info.get("duration")) or 3_000_000
            end_us = start_us + duration_us
        duration_us = max(0, end_us - start_us)
        asset_path = _materialize_asset(str(target), bundle["draft_dir"], "video", ".png")
        width, height = _infer_image_size(asset_path)
        material = _build_video_material(asset_path, duration_us, width, height)
        draft["materials"]["videos"].append(material)

        clip_override = {
            "alpha": float(info.get("alpha", alpha if alpha is not None else 1) or 1),
            "scale": {
                "x": float(info.get("scale_x", 1) or 1),
                "y": float(info.get("scale_y", 1) or 1),
            },
            "transform": {
                "x": float(info.get("transform_x", 0) or 0),
                "y": float(info.get("transform_y", 0) or 0),
            },
        }
        segment = _base_segment(material["id"], start_us, duration_us, 14000, clip_override=clip_override)
        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
    }


def append_captions(
    draft_id: str,
    captions: list[dict[str, Any]],
    *,
    alpha: Any = None,
    alignment: Any = None,
    border_color: str = "",
    font: str = "",
    font_size: Any = None,
    line_spacing: Any = None,
    scale_x: Any = None,
    scale_y: Any = None,
    style_text: Any = None,
    text_color: str = "#FFFFFF",
    transform_x: Any = None,
    transform_y: Any = None,
) -> dict[str, Any]:
    del style_text

    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "text", "text")
    items = []

    clip_alpha = float(alpha if alpha not in (None, "") else 1)
    clip_scale_x = float(scale_x if scale_x not in (None, "") else 1)
    clip_scale_y = float(scale_y if scale_y not in (None, "") else 1)
    clip_x = float(transform_x if transform_x not in (None, "") else 0)
    clip_y = float(transform_y if transform_y not in (None, "") else 0)
    material_font_size = float(font_size if font_size not in (None, "") else 15)
    material_line_spacing = float(line_spacing if line_spacing not in (None, "") else 0.02)
    material_alignment = int(float(alignment if alignment not in (None, "") else 1))

    for info in captions or []:
        if not isinstance(info, dict):
            continue
        text = str(info.get("text") or info.get("caption") or info.get("content") or "").strip()
        if not text:
            continue
        start_us = _duration_to_us(info.get("start"))
        end_us = _target_end_us(info)
        if end_us <= start_us:
            duration_us = _duration_to_us(info.get("duration")) or 2_000_000
            end_us = start_us + duration_us
        duration_us = max(0, end_us - start_us)

        material = _build_text_material(
            text=text,
            font_size=float(info.get("font_size", material_font_size) or material_font_size),
            text_color=str(info.get("text_color") or text_color or "#FFFFFF"),
            border_color=str(info.get("border_color") or border_color or ""),
            line_spacing=float(info.get("line_spacing", material_line_spacing) or material_line_spacing),
            alignment=int(float(info.get("alignment", material_alignment) or material_alignment)),
            font_name=str(info.get("font") or font or ""),
        )
        draft["materials"]["texts"].append(material)

        clip_override = {
            "alpha": float(info.get("alpha", clip_alpha) or clip_alpha),
            "scale": {
                "x": float(info.get("scale_x", clip_scale_x) or clip_scale_x),
                "y": float(info.get("scale_y", clip_scale_y) or clip_scale_y),
            },
            "transform": {
                "x": float(info.get("transform_x", clip_x) or clip_x),
                "y": float(info.get("transform_y", clip_y) or clip_y),
            },
        }
        segment = _base_segment(material["id"], start_us, duration_us, 15000, clip_override=clip_override)
        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
    }
