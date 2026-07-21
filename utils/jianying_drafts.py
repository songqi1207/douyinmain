#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local JianYing/CapCut draft creation helpers."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import tempfile
import time
import uuid
import zipfile
import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from utils.audio_probe import probe_audio_duration
from utils.local_media_generation import generated_local_path_from_url

try:
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is optional at runtime
    Image = None


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FALLBACK_DRAFT_ROOT = _PROJECT_ROOT / "temp" / "jianying_drafts"
_META_PATH = Path(__file__).resolve().parent / "data" / "jianying_meta.json"
_TRACK_RANK = {
    "video": 0,
    "audio": 1,
    "sticker": 2,
    "effect": 3,
    "filter": 4,
    "text": 5,
}
_REMOTE_TIMEOUT = 60

# Mihe's add_captions accepts the workflow-facing name "华文行楷" but writes
# JianYing's actual resource "毛笔行楷" into the resulting draft.
_FONT_ALIASES = {"华文行楷": "毛笔行楷"}
_FONT_META_OVERRIDES = {
    "毛笔行楷": {"resource_id": "6912033793700270606"},
    # 该字体不在 pyJianYingDraft 0.3.0 的资源表中，ID 来自可正常
    # 打开的“神”模板草稿。
    "出云龙": {"resource_id": "7618137748045696292"},
}

_jianying_meta_cache: dict[str, Any] | None = None
_draft_directory_cache: dict[tuple[str, str], Path] = {}


def _jianying_meta() -> dict[str, Any]:
    """剪映资源元数据表（特效/字体/动画 → resource_id/effect_id），源自 pyJianYingDraft。"""
    global _jianying_meta_cache
    if _jianying_meta_cache is None:
        try:
            _jianying_meta_cache = json.loads(_META_PATH.read_text(encoding="utf-8"))
        except Exception:
            _jianying_meta_cache = {}
    return _jianying_meta_cache


def _lookup_meta(table: str, name: str) -> dict[str, Any] | None:
    entry = _jianying_meta().get(table, {}).get(str(name or "").strip())
    return entry if isinstance(entry, dict) else None


def _resolve_font(font_name: str) -> tuple[str, dict[str, Any] | None]:
    canonical = _FONT_ALIASES.get(str(font_name or "").strip(), str(font_name or "").strip())
    meta = _lookup_meta("fonts", canonical) or _FONT_META_OVERRIDES.get(canonical)
    return canonical, meta


def _hex_to_rgb_floats(value: str, fallback: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> list[float]:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return list(fallback)
    try:
        return [round(int(raw[i : i + 2], 16) / 255.0, 6) for i in (0, 2, 4)]
    except ValueError:
        return list(fallback)


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


def _draft_cache_key(draft_root: Path, draft_id: str) -> tuple[str, str]:
    return os.path.normcase(str(draft_root.resolve())), str(draft_id).strip().lower()


def _safe_name(value: str, fallback: str = "coze_draft") -> str:
    raw = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in "-_ ")
    raw = raw.strip().replace(" ", "_")
    return raw[:80] or fallback


def _create_unique_draft_directory(draft_root: Path, draft_name: str) -> tuple[str, Path]:
    """Create a JianYing draft folder without changing its internal UUID.

    JianYing uses the folder name as the user-facing draft name.  Reusing a
    name therefore follows JianYing's ``name (1)``, ``name (2)`` convention,
    while ``draft_id`` remains an independent UUID in the draft metadata.
    """
    index = 0
    while True:
        resolved_name = draft_name if index == 0 else f"{draft_name} ({index})"
        draft_dir = draft_root / resolved_name
        try:
            draft_dir.mkdir(parents=False, exist_ok=False)
            return resolved_name, draft_dir
        except FileExistsError:
            index += 1


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
        "is_default_name": not track_name,
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
        "new_version": "110.0.0",
        "canvas_config": {
            "width": width,
            "height": height,
            "ratio": _ratio_from_size(width, height),
        },
        "config": {
            "adjust_max_index": 1,
            "attachment_info": [],
            "combination_max_index": 1,
            "export_range": None,
            "extract_audio_last_index": 1,
            "lyrics_recognition_id": "",
            "lyrics_sync": True,
            "lyrics_taskinfo": [],
            "maintrack_adsorb": True,
            "material_save_mode": 0,
            "multi_language_current": "none",
            "multi_language_list": [],
            "multi_language_main": "none",
            "multi_language_mode": "none",
            "original_sound_last_index": 1,
            "record_audio_last_index": 1,
            "sticker_max_index": 1,
            "subtitle_keywords_config": None,
            "subtitle_recognition_id": "",
            "subtitle_sync": True,
            "subtitle_taskinfo": [],
            "system_font_list": [],
            "video_mute": False,
            "zoom_info_params": None,
        },
        "platform": {
            "app_id": 3704,
            "app_source": "lv",
            "app_version": "5.9.0",
            "os": "windows",
        },
        "last_modified_platform": {
            "app_id": 3704,
            "app_source": "lv",
            "app_version": "5.9.0",
            "os": "windows",
        },
        "color_space": 0,
        "cover": None,
        "extra_info": None,
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
            "multi_language_refs": [],
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

    draft_root = _draft_root()
    cache_key = _draft_cache_key(draft_root, target_id)
    draft_dir = _draft_directory_cache.get(cache_key, draft_root / target_id)
    content_path = draft_dir / "draft_content.json"
    meta_path = draft_dir / "draft_meta_info.json"
    if not content_path.exists() or not meta_path.exists():
        lowered = target_id.lower()
        for candidate in draft_root.iterdir():
            if not candidate.is_dir():
                continue
            candidate_content = candidate / "draft_content.json"
            candidate_meta = candidate / "draft_meta_info.json"
            if not candidate_content.exists() or not candidate_meta.exists():
                continue

            matches_id = candidate.name.lower() == lowered
            if not matches_id:
                try:
                    metadata = json.loads(candidate_meta.read_text(encoding="utf-8"))
                    matches_id = str(metadata.get("draft_id") or "").strip().lower() == lowered
                except (OSError, json.JSONDecodeError):
                    matches_id = False
            if matches_id:
                draft_dir = candidate
                content_path = candidate_content
                meta_path = candidate_meta
                break
    if not content_path.exists() or not meta_path.exists():
        _draft_directory_cache.pop(cache_key, None)
        raise FileNotFoundError(f"draft not found: {target_id}")

    _draft_directory_cache[cache_key] = draft_dir

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
    requested_name = _safe_name(name, fallback=f"coze_draft_{suffix}")
    draft_name, draft_dir = _create_unique_draft_directory(draft_root, requested_name)
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
    _draft_directory_cache[_draft_cache_key(draft_root, draft_id)] = draft_dir
    return {
        "draft_id": draft_id,
        "draft_name": draft_name,
        "draft_dir": str(draft_dir),
        "width": width_int,
        "height": height_int,
        "ratio": bundle["content"]["canvas_config"]["ratio"],
        "message": "ok",
    }


def get_draft_info(draft_id: str) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    content = bundle["content"]
    meta = bundle["meta"]
    canvas = content.get("canvas_config") or {}
    return {
        "draft_id": str(meta.get("draft_id") or draft_id),
        "draft_name": str(meta.get("draft_name") or content.get("name") or ""),
        "draft_dir": str(bundle["draft_dir"]),
        "width": int(canvas.get("width") or 0),
        "height": int(canvas.get("height") or 0),
        "ratio": str(canvas.get("ratio") or "original"),
        "duration": int(content.get("duration") or 0),
        "message": "ok",
    }


def _deep_replace_paths(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {key: _deep_replace_paths(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_replace_paths(item, replacements) for item in value]
    if isinstance(value, str):
        text = value
        for old, new in replacements:
            if old:
                text = text.replace(old, new)
        return text
    return value


def _is_ip_host(hostname: str) -> bool:
    try:
        ipaddress.ip_address(str(hostname or "").strip())
        return True
    except ValueError:
        return False


def _looks_like_direct_host(hostname: str) -> bool:
    host = str(hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0"} or _is_ip_host(host)


def _normalize_remote_base_url(remote_base_url: str) -> str:
    raw = str(remote_base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        host = raw.split("/", 1)[0]
        scheme = "http" if _looks_like_direct_host(host.split(":", 1)[0]) or ":" in host else "https"
        raw = f"{scheme}://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme == "https" and _looks_like_direct_host(parsed.hostname or "") and parsed.port not in (None, 443):
        parsed = parsed._replace(scheme="http")
        return urlunparse(parsed).rstrip("/")
    return raw


def _candidate_archive_urls(draft_id: str, remote_base_url: str = "", package_url: str = "") -> list[str]:
    explicit = str(package_url or "").strip()
    if explicit:
        return [explicit]

    base_url = _normalize_remote_base_url(remote_base_url)
    if not base_url:
        return []

    candidates = [f"{base_url}/api/tools/export_draft_archive?draft_id={draft_id}"]
    parsed = urlparse(base_url)
    if parsed.scheme == "https" and _looks_like_direct_host(parsed.hostname or "") and parsed.port not in (None, 443):
        http_base = urlunparse(parsed._replace(scheme="http")).rstrip("/")
        fallback = f"{http_base}/api/tools/export_draft_archive?draft_id={draft_id}"
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _http_get_without_proxy(url: str, timeout: int, stream: bool = False) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    return session.get(url, timeout=timeout, stream=stream)


def export_draft_archive(draft_id: str) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft_dir = Path(bundle["draft_dir"])
    export_root = _PROJECT_ROOT / "temp" / "exported_drafts"
    export_root.mkdir(parents=True, exist_ok=True)
    archive_path = export_root / f"{draft_dir.name}.zip"

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in draft_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(draft_dir))

    return {
        "draft_id": str(bundle["meta"].get("draft_id") or draft_id),
        "draft_dir": str(draft_dir),
        "archive_path": str(archive_path),
        "message": "ok",
    }


def import_remote_draft(
    draft_id: str,
    remote_base_url: str = "",
    package_url: str = "",
    force: Any = False,
) -> dict[str, Any]:
    target_id = str(draft_id or "").strip()
    if not target_id:
        raise ValueError("missing draft_id")

    force_flag = str(force).strip().lower() in {"1", "true", "yes", "on"} if not isinstance(force, bool) else force
    archive_candidates = _candidate_archive_urls(
        draft_id=target_id,
        remote_base_url=remote_base_url,
        package_url=package_url,
    )
    if not archive_candidates:
        raise ValueError("missing remote_base_url or package_url")

    draft_root = _draft_root()
    target_dir = draft_root / target_id
    if target_dir.exists():
        if force_flag:
            shutil.rmtree(target_dir, ignore_errors=True)
        else:
            existing = get_draft_info(target_id)
            existing["already_exists"] = True
            existing["message"] = "draft already exists locally"
            return existing

    with tempfile.TemporaryDirectory(prefix="draft_import_") as temp_dir:
        archive_path = Path(temp_dir) / f"{target_id}.zip"
        response = None
        last_error = None
        archive_url = archive_candidates[0]
        for candidate in archive_candidates:
            archive_url = candidate
            try:
                response = _http_get_without_proxy(candidate, timeout=_REMOTE_TIMEOUT, stream=True)
                response.raise_for_status()
                break
            except Exception as exc:
                last_error = exc
                response = None
        if response is None:
            raise RuntimeError(
                f"failed to download remote draft archive from {archive_url}: "
                + (str(last_error) if last_error else "unknown error")
            )
        with archive_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fh.write(chunk)

        extract_dir = Path(temp_dir) / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)

        content_path = extract_dir / "draft_content.json"
        meta_path = extract_dir / "draft_meta_info.json"
        if not content_path.exists() or not meta_path.exists():
            raise FileNotFoundError("invalid draft archive: missing core json files")

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        content = json.loads(content_path.read_text(encoding="utf-8"))

        old_dir = str(meta.get("draft_fold_path") or "")
        old_root = str(meta.get("draft_root_path") or "")

        target_dir.mkdir(parents=True, exist_ok=True)
        for item in extract_dir.iterdir():
            dest = target_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        replacements = [
            (old_dir, str(target_dir)),
            (old_root, str(draft_root)),
        ]
        content = _deep_replace_paths(content, replacements)
        meta = _deep_replace_paths(meta, replacements)
        meta["draft_id"] = target_id
        meta["draft_fold_path"] = str(target_dir)
        meta["draft_root_path"] = str(draft_root)
        meta["draft_name"] = str(meta.get("draft_name") or content.get("name") or target_id)

        imported_bundle = {
            "draft_dir": target_dir,
            "content": content,
            "meta": meta,
        }
        _write_bundle(imported_bundle)

    result = get_draft_info(target_id)
    result["source_archive_url"] = archive_url
    result["message"] = "ok"
    return result


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

    generated_local_path = generated_local_path_from_url(raw)
    if generated_local_path is not None:
        suffix = generated_local_path.suffix or fallback_ext
        asset_path = asset_dir / f"{_generate_id()}{suffix}"
        shutil.copy2(generated_local_path, asset_path)
        return asset_path

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
    material_id = _generate_id()
    return {
        "id": material_id,
        "app_id": 0,
        "category_id": "",
        "category_name": "local",
        "check_flag": 3,
        "copyright_limit_type": "none",
        "duration": duration_us,
        "effect_id": "",
        "formula_id": "",
        "intensifies_path": "",
        "local_material_id": material_id,
        "music_id": material_id,
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


def _build_video_material(
    path: Path,
    duration_us: int,
    width: int,
    height: int,
    *,
    media_type: str = "photo",
    has_audio: bool = False,
) -> dict[str, Any]:
    material_id = _generate_id()
    return {
        "id": material_id,
        "audio_fade": None,
        "category_id": "",
        "category_name": "local",
        "check_flag": 63487,
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
        "has_audio": has_audio,
        "height": height,
        "intensifies_audio_path": "",
        "intensifies_path": "",
        "is_unified_beauty_mode": False,
        "local_id": "",
        "local_material_id": "",
        "material_id": material_id,
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
        "type": media_type,
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


def _build_text_material(
    text: str,
    font_size: float,
    text_color: str,
    border_color: str,
    line_spacing: float,
    alignment: int,
    font_name: str,
    letter_spacing: float = 0,
    style_text: Any = None,
) -> dict[str, Any]:
    # 结构对齐 pyJianYingDraft（真机验证过的最小字段集）：
    # range 为字符数而非字节数，颜色为 0-1 RGB 数组，描边放 styles[].strokes。
    style: dict[str, Any] = {
        "range": [0, len(text)],
        "size": font_size,
        "bold": False,
        "italic": False,
        "underline": False,
        "fill": {
            "alpha": 1.0,
            "content": {
                "render_type": "solid",
                "solid": {"alpha": 1.0, "color": _hex_to_rgb_floats(text_color)},
            },
        },
        "strokes": [],
    }

    border_raw = str(border_color or "").strip().lstrip("#")
    if len(border_raw) == 8 and border_raw[:2].lower() == "00":
        border_color = ""  # #00AARRGGBB 全透明描边 = 无描边

    check_flag = 7
    if border_color:
        check_flag |= 8
        style["strokes"] = [
            {
                "content": {"solid": {"alpha": 1.0, "color": _hex_to_rgb_floats(border_color, (0.0, 0.0, 0.0))}},
                "width": 0.08,
            }
        ]

    canonical_font_name, font_meta = _resolve_font(font_name)
    if font_meta:
        # 剪映按 resource id 拉取字体；保留真实字体名可以避免回退到系统默认字体。
        style["font"] = {
            "id": font_meta.get("resource_id", ""),
            "path": f"{canonical_font_name}.ttf",
        }

    parsed_style = style_text
    if isinstance(parsed_style, str) and parsed_style.strip():
        try:
            parsed_style = json.loads(parsed_style)
        except json.JSONDecodeError:
            parsed_style = None
    if isinstance(parsed_style, dict):
        parsed_style = parsed_style.get("style", parsed_style)
        if isinstance(parsed_style, dict):
            for key in ("bold", "italic", "underline", "fill", "strokes", "shadows"):
                if key in parsed_style:
                    style[key] = parsed_style[key]

    style_payload = {"styles": [style], "text": text}
    material = {
        "id": _generate_id(),
        "type": "text",
        "content": json.dumps(style_payload, ensure_ascii=False, separators=(",", ":")),
        "alignment": alignment,
        "typesetting": 0,
        "letter_spacing": letter_spacing * 0.05,
        "line_spacing": 0.02 + line_spacing * 0.05,
        "line_feed": 1,
        "line_max_width": 0.82,
        "force_apply_line_max_width": False,
        "check_flag": check_flag,
        "global_alpha": 1.0,
        "font_name": canonical_font_name,
    }
    if font_meta:
        resource_id = str(font_meta.get("resource_id") or "")
        material.update(
            {
                "font_id": resource_id,
                "font_resource_id": "",
                "font_path": "",
                "font_title": "none",
                "fonts": [
                    {
                        "effect_id": resource_id,
                        "id": resource_id,
                        "path": f"{canonical_font_name}.ttf",
                        "resource_id": resource_id,
                        "title": canonical_font_name,
                    }
                ],
            }
        )
    return material


def _new_speed_material() -> dict[str, Any]:
    return {
        "curve_speed": None,
        "id": _generate_id(),
        "mode": 0,
        "speed": 1.0,
        "type": "speed",
    }


def _base_segment(
    material_id: str,
    start_us: int,
    duration_us: int,
    render_index: int,
    clip_override: dict[str, Any] | None = None,
    *,
    kind: str = "video",
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    segment = {
        "id": _generate_id(),
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "enable_adjust": True,
        "enable_color_correct_adjust": False,
        "enable_color_curves": True,
        "enable_color_match_adjust": False,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "last_nonzero_volume": 1.0,
        "visible": True,
        "common_keyframes": [],
        "keyframe_refs": [],
        "extra_material_refs": [],
        "render_index": render_index,
        "track_render_index": 0,
        "track_attribute": 0,
        "reverse": False,
    }

    if kind == "effect":
        return segment

    # 音/视/文本片段：speed 配套素材是剪映打开草稿的硬性要求
    segment["source_timerange"] = None if kind == "text" else {"start": 0, "duration": duration_us}
    segment["speed"] = 1.0
    segment["volume"] = 1.0
    segment["is_tone_modify"] = False
    if draft is not None:
        speed_material = _new_speed_material()
        draft["materials"]["speeds"].append(speed_material)
        segment["extra_material_refs"].append(speed_material["id"])

    if kind in {"video", "text"}:
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
                elif key == "flip":
                    clip["flip"].update(value or {})
        segment["clip"] = clip
        segment["uniform_scale"] = {"on": True, "value": 1.0}

    if kind == "video":
        segment["hdr_settings"] = {"intensity": 1.0, "mode": 1, "nits": 1000}

    return segment


def _find_segment_by_id(draft: dict[str, Any], segment_id: str) -> dict[str, Any] | None:
    target = str(segment_id or "").strip()
    if not target:
        return None
    for track in draft.get("tracks", []):
        for segment in track.get("segments", []):
            if str(segment.get("id", "")) == target:
                return segment
    return None


def _normalize_keyframe_property(value: str) -> str:
    raw = str(value or "").strip()
    mapping = {
        "UNIFORM_SCALE": "KFTypeUniformScale",
        "KFTypeUniformScale": "KFTypeUniformScale",
        "KFTypePositionX": "KFTypePositionX",
        "KFTypePositionY": "KFTypePositionY",
        "KFTypeRotation": "KFTypeRotation",
        "KFTypeScaleX": "KFTypeScaleX",
        "KFTypeScaleY": "KFTypeScaleY",
        "KFTypeAlpha": "KFTypeAlpha",
        "KFTypeVolume": "KFTypeVolume",
    }
    return mapping.get(raw, raw or "KFTypePositionX")


def _build_effect_material(effect_name: str) -> tuple[dict[str, Any], bool]:
    """按名字从元数据表解析特效，返回 (素材, 是否命中元数据)。

    未命中时只能把入参当 effect_id 使用，剪映端大概率无法加载对应资源。
    """
    name = str(effect_name or "").strip()
    meta = _lookup_meta("video_scene_effects", name) or _lookup_meta("video_character_effects", name)
    effect_type = "video_effect"
    if meta is None:
        resource_id = ""
        effect_id = name
        adjust_params: list[dict[str, Any]] = []
    else:
        if _lookup_meta("video_scene_effects", name) is None:
            effect_type = "face_effect"
        resource_id = str(meta.get("resource_id", ""))
        effect_id = str(meta.get("effect_id", ""))
        adjust_params = [
            {
                "default_value": param.get("default_value", 0.0),
                "max_value": param.get("max_value", 1.0),
                "min_value": param.get("min_value", 0.0),
                "name": param.get("name", ""),
                "parameterIndex": index,
                "portIndex": 0,
                "value": param.get("default_value", 0.0),
            }
            for index, param in enumerate(meta.get("params", []))
        ]

    material = {
        "adjust_params": adjust_params,
        "apply_target_type": 2,
        "apply_time_range": None,
        "category_id": "",
        "category_name": "",
        "common_keyframes": [],
        "disable_effect_faces": [],
        "effect_id": effect_id,
        "formula_id": "",
        "id": _generate_id(),
        "name": name,
        "platform": "all",
        "render_index": 11000,
        "resource_id": resource_id,
        "source_platform": 0,
        "time_range": None,
        "track_render_index": 0,
        "type": effect_type,
        "value": 1.0,
        "version": "",
    }
    return material, meta is not None


def _build_animation_material(animations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": _generate_id(),
        "type": "sticker_animation",
        "multi_language_current": "none",
        "animations": animations,
    }


def _resolve_video_animation(name: str, animation_type: str, start_us: int, duration_us: Any) -> dict[str, Any] | None:
    table = {"in": "video_intros", "out": "video_outros", "group": "video_group_animations"}[animation_type]
    meta = _lookup_meta(table, name)
    if meta is None:
        return None
    duration = _duration_to_us(duration_us) or int(meta.get("duration_us") or 500_000)
    return {
        "anim_adjust_params": None,
        "platform": "all",
        "panel": "video",
        "material_type": "video",
        "name": str(name).strip(),
        "id": str(meta.get("effect_id", "")),
        "type": animation_type,
        "resource_id": str(meta.get("resource_id", "")),
        "start": start_us,
        "duration": duration,
    }


def _resolve_text_animation(name: str, animation_type: str, start_us: int, duration_us: Any) -> dict[str, Any] | None:
    table = {
        "in": "text_intros",
        "out": "text_outros",
        "loop": "text_loops",
    }[animation_type]
    meta = _lookup_meta(table, name)
    if meta is None:
        return None

    duration = _duration_to_us(duration_us)
    if duration <= 0:
        # pyJianYingDraft 的元数据以纳秒保存默认时长，而草稿时间轴使用
        # 微秒；例如 500000000000 表示 0.5 秒。
        meta_duration = int(meta.get("duration_us") or 500_000_000_000)
        duration = meta_duration // 1_000_000 if meta_duration > 60_000_000 else meta_duration

    category = {
        "in": ("ruchang", "入场"),
        "out": ("chuchang", "出场"),
        "loop": ("xunhuan", "循环"),
    }[animation_type]
    return {
        "anim_adjust_params": None,
        "platform": "all",
        "panel": "",
        "material_type": "sticker",
        "name": str(name).strip(),
        "id": str(meta.get("effect_id", "")),
        "type": animation_type,
        "resource_id": str(meta.get("resource_id", "")),
        "start": start_us,
        "duration": duration,
        "path": "",
        "request_id": "",
        "category_id": category[0],
        "category_name": category[1],
    }


def append_audios(
    draft_id: str,
    audio_infos: list[dict[str, Any]],
    *,
    track_name: str | None = None,
    render_index: int | None = None,
) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "audio", track_name or "audio")
    segment_render_index = int(render_index) if render_index is not None else 11000
    items = []
    audio_ids = []

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
        audio_ids.append(material["id"])

        segment = _base_segment(material["id"], start_us, duration_us, segment_render_index, kind="audio", draft=draft)
        segment["volume"] = float(info.get("volume", 1) or 1)
        segment["last_nonzero_volume"] = segment["volume"] or 1.0
        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "audio_ids": audio_ids,
        "message": "ok",
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
    }


def append_images(
    draft_id: str,
    image_infos: list[dict[str, Any]],
    alpha: Any = None,
    *,
    track_name: str | None = None,
    render_index: int | None = None,
) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "video", track_name or "video")
    segment_render_index = int(render_index) if render_index is not None else 14000
    items = []
    warnings: list[str] = []

    for info in image_infos or []:
        if not isinstance(info, dict):
            continue
        video_target = info.get("video_url")
        target = video_target or info.get("image_url") or info.get("img") or info.get("url") or info.get("path") or info.get("file_path")
        if not target:
            continue
        start_us = _duration_to_us(info.get("start"))
        end_us = _target_end_us(info)
        if end_us <= start_us:
            duration_us = _duration_to_us(info.get("duration")) or 3_000_000
            end_us = start_us + duration_us
        duration_us = max(0, end_us - start_us)
        video_suffixes = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
        is_video = bool(video_target) or Path(urlparse(str(target)).path).suffix.lower() in video_suffixes
        asset_path = _materialize_asset(
            str(target),
            bundle["draft_dir"],
            "video",
            ".mp4" if is_video else ".png",
        )
        if is_video:
            canvas = draft.get("canvas_config") or {}
            width = int(float(info.get("width") or canvas.get("width") or 1920))
            height = int(float(info.get("height") or canvas.get("height") or 1080))
        else:
            width, height = _infer_image_size(asset_path)
        material = _build_video_material(
            asset_path,
            duration_us,
            width,
            height,
            media_type="video" if is_video else "photo",
            has_audio=bool(info.get("has_audio", False)) if is_video else False,
        )
        draft["materials"]["videos"].append(material)

        clip_override = {
            "alpha": float(info.get("alpha", alpha if alpha is not None else 1) or 1),
            "rotation": float(info.get("rotation", 0) or 0),
            "flip": {
                "horizontal": bool(info.get("flip_horizontal", False)),
                "vertical": bool(info.get("flip_vertical", False)),
            },
            "scale": {
                "x": float(info.get("scale_x", 1) or 1),
                "y": float(info.get("scale_y", 1) or 1),
            },
            "transform": {
                "x": float(info.get("transform_x", 0) or 0),
                "y": float(info.get("transform_y", 0) or 0),
            },
        }
        segment = _base_segment(material["id"], start_us, duration_us, segment_render_index, clip_override=clip_override, kind="video", draft=draft)

        animations = []
        in_name = str(info.get("in_animation") or "").strip()
        if in_name:
            animation = _resolve_video_animation(in_name, "in", 0, info.get("in_animation_duration"))
            if animation is None:
                warnings.append(f"未知入场动画已忽略: {in_name}")
            else:
                animations.append(animation)
        out_name = str(info.get("out_animation") or "").strip()
        if out_name:
            animation = _resolve_video_animation(out_name, "out", 0, info.get("out_animation_duration"))
            if animation is None:
                warnings.append(f"未知出场动画已忽略: {out_name}")
            else:
                animation["start"] = max(0, duration_us - animation["duration"])
                animations.append(animation)
        group_name = str(info.get("group_animation") or "").strip()
        if group_name:
            animation = _resolve_video_animation(group_name, "group", 0, info.get("group_animation_duration"))
            if animation is None:
                warnings.append(f"未知组合动画已忽略: {group_name}")
            else:
                animation["duration"] = min(duration_us, animation["duration"])
                animations.append(animation)
        if animations:
            animation_material = _build_animation_material(animations)
            draft["materials"]["material_animations"].append(animation_material)
            segment["extra_material_refs"].append(animation_material["id"])

        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
        "warnings": warnings,
    }


def append_videos(
    draft_id: str,
    video_infos: list[dict[str, Any]],
    alpha: Any = None,
    *,
    track_name: str | None = None,
    render_index: int | None = None,
) -> dict[str, Any]:
    normalized = []
    for info in video_infos or []:
        if not isinstance(info, dict):
            continue
        copied = dict(info)
        if not copied.get("video_url"):
            copied["video_url"] = copied.get("url") or copied.get("path") or copied.get("file_path")
        normalized.append(copied)
    return append_images(
        draft_id,
        normalized,
        alpha,
        track_name=track_name,
        render_index=render_index,
    )


def append_captions(
    draft_id: str,
    captions: list[dict[str, Any]],
    *,
    alpha: Any = None,
    alignment: Any = None,
    border_color: str = "",
    font: str = "",
    font_size: Any = None,
    letter_spacing: Any = None,
    line_spacing: Any = None,
    scale_x: Any = None,
    scale_y: Any = None,
    style_text: Any = None,
    text_color: str = "#FFFFFF",
    transform_x: Any = None,
    transform_y: Any = None,
    rotation: Any = None,
    flip_horizontal: Any = None,
    flip_vertical: Any = None,
    in_animation: str | None = None,
    in_animation_duration: Any = None,
    out_animation: str | None = None,
    out_animation_duration: Any = None,
    loop_animation: str | None = None,
    loop_animation_duration: Any = None,
    track_name: str | None = None,
    render_index: int | None = None,
) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "text", track_name or "text")
    segment_render_index = int(render_index) if render_index is not None else 15000
    items = []
    warnings: list[str] = []

    clip_alpha = float(alpha if alpha not in (None, "") else 1)
    clip_scale_x = float(scale_x if scale_x not in (None, "") else 1)
    clip_scale_y = float(scale_y if scale_y not in (None, "") else 1)
    clip_x = float(transform_x if transform_x not in (None, "") else 0)
    clip_y = float(transform_y if transform_y not in (None, "") else 0)
    material_font_size = float(font_size if font_size not in (None, "") else 15)
    material_letter_spacing = float(letter_spacing if letter_spacing not in (None, "") else 0)
    material_line_spacing = float(line_spacing if line_spacing not in (None, "") else 0)
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
            letter_spacing=float(info.get("letter_spacing", material_letter_spacing) or material_letter_spacing),
            style_text=info.get("style_text", style_text),
        )
        draft["materials"]["texts"].append(material)

        clip_override = {
            "alpha": float(info.get("alpha", clip_alpha) or clip_alpha),
            "rotation": float(info.get("rotation", rotation or 0) or 0),
            "flip": {
                "horizontal": bool(info.get("flip_horizontal", flip_horizontal or False)),
                "vertical": bool(info.get("flip_vertical", flip_vertical or False)),
            },
            "scale": {
                "x": float(info.get("scale_x", clip_scale_x) or clip_scale_x),
                "y": float(info.get("scale_y", clip_scale_y) or clip_scale_y),
            },
            "transform": {
                "x": float(info.get("transform_x", clip_x) or clip_x),
                "y": float(info.get("transform_y", clip_y) or clip_y),
            },
        }
        segment = _base_segment(material["id"], start_us, duration_us, segment_render_index, clip_override=clip_override, kind="text", draft=draft)

        animations = []
        animation_specs = (
            ("in", info.get("in_animation") or in_animation, info.get("in_animation_duration") or in_animation_duration),
            ("out", info.get("out_animation") or out_animation, info.get("out_animation_duration") or out_animation_duration),
            ("loop", info.get("loop_animation") or loop_animation, info.get("loop_animation_duration") or loop_animation_duration),
        )
        animation_labels = {"in": "入场", "out": "出场", "loop": "循环"}
        for animation_type, animation_name, animation_duration in animation_specs:
            resolved_name = str(animation_name or "").strip()
            if not resolved_name:
                continue
            animation = _resolve_text_animation(resolved_name, animation_type, 0, animation_duration)
            if animation is None:
                warnings.append(f"未知文字{animation_labels[animation_type]}动画已忽略: {resolved_name}")
                continue
            animation["duration"] = min(duration_us, animation["duration"])
            if animation_type == "out":
                animation["start"] = max(0, duration_us - animation["duration"])
            animations.append(animation)
        if animations:
            animation_material = _build_animation_material(animations)
            draft["materials"]["material_animations"].append(animation_material)
            segment["extra_material_refs"].append(animation_material["id"])

        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
        "warnings": warnings,
    }


def append_keyframes(draft_id: str, keyframes: list[dict[str, Any]]) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    applied = 0

    for item in keyframes or []:
        if not isinstance(item, dict):
            continue
        segment_id = str(item.get("segment_id") or item.get("id") or "").strip()
        segment = _find_segment_by_id(draft, segment_id)
        if segment is None:
            continue

        property_type = _normalize_keyframe_property(str(item.get("property") or item.get("property_type") or ""))
        try:
            offset_us = max(0, int(round(float(item.get("offset", 0) or 0))))
            value_num = float(item.get("value", 0) or 0)
        except (TypeError, ValueError):
            continue

        existing = None
        for keyframe_group in segment.get("common_keyframes", []):
            if str(keyframe_group.get("property_type", "")) == property_type:
                existing = keyframe_group
                break
        if existing is None:
            existing = {"id": _generate_id(), "material_id": "", "property_type": property_type, "keyframe_list": []}
            segment.setdefault("common_keyframes", []).append(existing)

        existing["keyframe_list"].append(
            {
                "id": _generate_id(),
                "time_offset": offset_us,
                "values": [value_num],
                "curveType": "Line",
                "graphID": "",
                "left_control": {"x": 0.0, "y": 0.0},
                "right_control": {"x": 0.0, "y": 0.0},
            }
        )
        existing["keyframe_list"].sort(key=lambda row: int(row.get("time_offset") or 0))
        applied += 1

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "applied": applied,
    }


def append_effects(
    draft_id: str,
    effect_infos: list[dict[str, Any]],
    *,
    track_name: str | None = None,
    render_index: int | None = None,
) -> dict[str, Any]:
    bundle = _load_bundle(draft_id)
    draft = bundle["content"]
    track = _ensure_track(draft, "effect", track_name or "effect")
    segment_render_index = int(render_index) if render_index is not None else 16000
    items = []
    effect_ids = []
    warnings: list[str] = []

    for info in effect_infos or []:
        if not isinstance(info, dict):
            continue
        effect_name = str(info.get("effect") or info.get("name") or info.get("effect_id") or "").strip()
        if not effect_name:
            continue
        start_us = _duration_to_us(info.get("start"))
        end_us = _target_end_us(info)
        if end_us <= start_us:
            duration_us = _duration_to_us(info.get("duration")) or 500_000
            end_us = start_us + duration_us
        duration_us = max(0, end_us - start_us)

        material, resolved = _build_effect_material(effect_name)
        if not resolved:
            warnings.append(f"特效名未命中元数据表，剪映可能无法加载: {effect_name}")
        draft["materials"]["video_effects"].append(material)
        effect_ids.append(material["id"])

        segment = _base_segment(material["id"], start_us, duration_us, segment_render_index, kind="effect")
        track["segments"].append(segment)
        items.append({"id": segment["id"], "start": start_us, "end": end_us, "effect": effect_name})

    _write_bundle(bundle)
    return {
        "draft_id": draft_id,
        "message": "ok",
        "effect_ids": effect_ids,
        "segment_ids": [item["id"] for item in items],
        "segment_infos": items,
        "track_id": track["id"],
        "warnings": warnings,
    }
