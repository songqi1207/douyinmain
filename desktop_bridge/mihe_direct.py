#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Direct importer for drafts stored by Mihe's legacy Coze plugin."""

from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

import utils.jianying_drafts as jianying


ProgressCallback = Callable[[str], None]
AssetDownloader = Callable[[str, Path], None]

MIHE_DRAFT_ENDPOINT = "https://miheai.com/plugin/draft/{draft_id}"
_DRAFT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_REMOTE_TIMEOUT = (15, 180)
_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024


class MiheDirectError(RuntimeError):
    pass


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)


def validate_mihe_server_draft_id(value: str) -> str:
    draft_id = str(value or "").strip().strip('"').strip("'")
    if not _DRAFT_ID_PATTERN.fullmatch(draft_id):
        raise MiheDirectError("米核服务器 draft_id 应为标准 UUID，例如 xxxxxxxx-xxxx-4xxx-xxxx-xxxxxxxxxxxx")
    return draft_id.lower()


def fetch_mihe_draft_json(
    draft_id: str,
    *,
    endpoint_template: str = MIHE_DRAFT_ENDPOINT,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    normalized = validate_mihe_server_draft_id(draft_id)
    url = endpoint_template.format(draft_id=normalized)
    client = session or requests.Session()
    try:
        response = client.get(
            url,
            timeout=_REMOTE_TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "DouyinDraftBridge/1.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise MiheDirectError(f"读取米核服务器草稿失败：{exc}") from exc
    except ValueError as exc:
        raise MiheDirectError("米核服务器返回的不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise MiheDirectError("米核服务器返回的数据结构不正确")
    if not isinstance(payload.get("tracks"), list):
        message = str(payload.get("message") or "草稿不存在或已过期")
        raise MiheDirectError(message)
    materials = payload.get("materials")
    if not isinstance(materials, dict):
        raise MiheDirectError("米核草稿 JSON 缺少 materials")
    return payload


def summarize_mihe_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a navigable index without changing the server's original JSON."""
    tracks = payload.get("tracks") or []
    materials = payload.get("materials") or {}
    material_lookup: dict[str, dict[str, Any]] = {}
    material_categories: list[dict[str, Any]] = []

    for category, values in materials.items():
        if not isinstance(values, list):
            continue
        identifiers: list[str] = []
        for index, material in enumerate(values):
            if not isinstance(material, dict):
                continue
            material_id = str(material.get("id") or "")
            if material_id:
                identifiers.append(material_id)
                material_lookup[material_id] = {
                    "category": category,
                    "index": index,
                    "json_path": f"$.materials.{category}[{index}]",
                }
        material_categories.append(
            {
                "category": category,
                "count": len(values),
                "ids": identifiers,
                "json_path": f"$.materials.{category}",
            }
        )

    track_index: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    segment_count = 0
    for track_number, track in enumerate(tracks):
        if not isinstance(track, dict):
            continue
        segments = track.get("segments") or []
        track_entry = {
            "index": track_number,
            "id": track.get("id"),
            "type": track.get("type"),
            "name": track.get("name"),
            "segment_count": len(segments) if isinstance(segments, list) else 0,
            "json_path": f"$.tracks[{track_number}]",
            "segments": [],
        }
        if not isinstance(segments, list):
            track_index.append(track_entry)
            continue
        for segment_number, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            segment_count += 1
            material_id = str(segment.get("material_id") or "")
            material_location = material_lookup.get(material_id)
            keyframes = segment.get("common_keyframes") or []
            property_types = [
                item.get("property_type")
                for item in keyframes
                if isinstance(item, dict) and item.get("property_type") is not None
            ]
            segment_path = f"$.tracks[{track_number}].segments[{segment_number}]"
            track_entry["segments"].append(
                {
                    "index": segment_number,
                    "id": segment.get("id"),
                    "material_id": material_id or None,
                    "material_category": material_location.get("category") if material_location else None,
                    "material_json_path": material_location.get("json_path") if material_location else None,
                    "source_timerange": segment.get("source_timerange"),
                    "target_timerange": segment.get("target_timerange"),
                    "render_index": segment.get("render_index"),
                    "keyframe_property_types": property_types,
                    "json_path": segment_path,
                }
            )
            if material_id:
                references.append(
                    {
                        "segment_json_path": segment_path,
                        "material_id": material_id,
                        "material_category": material_location.get("category") if material_location else None,
                        "material_json_path": material_location.get("json_path") if material_location else None,
                    }
                )
        track_index.append(track_entry)

    return {
        "top_level_keys": sorted(payload.keys()),
        "duration": payload.get("duration"),
        "canvas_config": payload.get("canvas_config"),
        "track_count": len(tracks) if isinstance(tracks, list) else 0,
        "segment_count": segment_count,
        "material_category_count": len(material_categories),
        "material_count": sum(item["count"] for item in material_categories),
        "material_categories": material_categories,
        "tracks": track_index,
        "segment_material_references": references,
        "notes": {
            "raw_json": "mihe_server_draft.json 是服务器原始响应，未修改任何字段",
            "json_path": "索引中的 $.tracks[0] 形式表示原始 JSON 中的准确位置",
        },
    }


def export_mihe_server_draft_json(
    draft_id: str,
    *,
    output_dir: Path | str,
    server_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export the untouched Mihe response plus a human-readable structure index."""
    normalized = validate_mihe_server_draft_id(draft_id)
    payload = server_payload if server_payload is not None else fetch_mihe_draft_json(normalized)
    if not isinstance(payload, dict) or not isinstance(payload.get("tracks"), list):
        raise MiheDirectError("米核草稿 JSON 缺少 tracks")
    if not isinstance(payload.get("materials"), dict):
        raise MiheDirectError("米核草稿 JSON 缺少 materials")

    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    raw_path = target / "mihe_server_draft.json"
    index_path = target / "mihe_draft_structure.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = summarize_mihe_draft(payload)
    index_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "draft_id": normalized,
        "output_dir": str(target),
        "raw_json_path": str(raw_path),
        "structure_path": str(index_path),
        "track_count": summary["track_count"],
        "segment_count": summary["segment_count"],
        "material_count": summary["material_count"],
    }


def _download_asset(url: str, destination: Path) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MiheDirectError(f"素材不是可下载的 HTTP/HTTPS 地址：{url}")
    last_error: Exception | None = None
    for attempt in range(3):
        temporary = destination.with_suffix(destination.suffix + ".download")
        temporary.unlink(missing_ok=True)
        try:
            with requests.get(url, stream=True, timeout=_REMOTE_TIMEOUT) as response:
                response.raise_for_status()
                declared = int(response.headers.get("Content-Length") or 0)
                if declared > _MAX_ASSET_BYTES:
                    raise MiheDirectError(f"素材超过 2GB 安全限制：{url}")
                written = 0
                with temporary.open("wb") as stream:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if not block:
                            continue
                        written += len(block)
                        if written > _MAX_ASSET_BYTES:
                            raise MiheDirectError(f"素材超过 2GB 安全限制：{url}")
                        stream.write(block)
            temporary.replace(destination)
            return
        except Exception as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt < 2:
                time.sleep(attempt + 1)
    raise MiheDirectError(f"素材下载失败：{url}：{last_error}")


def _merge_duplicate_keyframes(content: dict[str, Any]) -> None:
    for track in content.get("tracks") or []:
        for segment in track.get("segments") or []:
            keyframes = segment.get("common_keyframes")
            if not isinstance(keyframes, list) or len(keyframes) < 2:
                continue
            merged: dict[Any, dict[str, Any]] = {}
            order: list[Any] = []
            for keyframe in keyframes:
                if not isinstance(keyframe, dict):
                    continue
                property_type = keyframe.get("property_type")
                if property_type not in merged:
                    merged[property_type] = keyframe
                    order.append(property_type)
                    continue
                existing = merged[property_type].setdefault("keyframe_list", [])
                incoming = keyframe.get("keyframe_list") or []
                if isinstance(existing, list) and isinstance(incoming, list):
                    existing.extend(incoming)
            segment["common_keyframes"] = [merged[item] for item in order]


def _existing_report(draft_dir: Path, draft_id: str) -> dict[str, Any] | None:
    content_path = draft_dir / "draft_content.json"
    meta_path = draft_dir / "draft_meta_info.json"
    if not content_path.is_file() or not meta_path.is_file():
        return None
    content = json.loads(content_path.read_text(encoding="utf-8"))
    tracks = content.get("tracks") or []
    return {
        "draft_id": draft_id,
        "draft_name": draft_id,
        "draft_dir": str(draft_dir),
        "already_imported": True,
        "verified": True,
        "track_count": len(tracks),
        "segment_count": sum(len(track.get("segments") or []) for track in tracks),
        "method": "mihe_direct_http",
        "warnings": [],
        "message": "ok",
    }


def import_mihe_server_draft(
    draft_id: str,
    *,
    draft_root: Path | str,
    progress: ProgressCallback | None = None,
    server_payload: dict[str, Any] | None = None,
    asset_downloader: AssetDownloader | None = None,
) -> dict[str, Any]:
    """Download a server draft and materialize it as a local JianYing draft."""
    normalized = validate_mihe_server_draft_id(draft_id)
    root = Path(draft_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target_dir = root / normalized
    existing = _existing_report(target_dir, normalized) if target_dir.exists() else None
    if existing:
        _progress(progress, "该米核草稿已导入，直接返回本地结果")
        return existing
    if target_dir.exists():
        raise MiheDirectError(f"目标目录已存在但不是完整草稿，请人工检查：{target_dir}")

    _progress(progress, "正在直接读取米核服务器草稿 JSON……")
    raw_payload = server_payload if server_payload is not None else fetch_mihe_draft_json(normalized)
    if not isinstance(raw_payload, dict) or not isinstance(raw_payload.get("tracks"), list):
        raise MiheDirectError("测试或服务器草稿 JSON 缺少 tracks")
    if not isinstance(raw_payload.get("materials"), dict):
        raise MiheDirectError("测试或服务器草稿 JSON 缺少 materials")
    content = copy.deepcopy(raw_payload)
    _merge_duplicate_keyframes(content)

    materials = content.get("materials") or {}
    audios = materials.get("audios") or []
    videos = materials.get("videos") or []
    if not isinstance(audios, list) or not isinstance(videos, list):
        raise MiheDirectError("米核草稿的音视频素材列表结构不正确")

    asset_group = str(uuid.uuid4()).upper()
    final_asset_dir = target_dir / asset_group
    download = asset_downloader or _download_asset
    downloaded = 0
    with tempfile.TemporaryDirectory(prefix=".mihe-import-", dir=str(root)) as temporary:
        staging = Path(temporary)
        staging_assets = staging / asset_group
        staging_assets.mkdir(parents=True, exist_ok=True)

        material_specs = [
            *((material, ".mp3") for material in audios if isinstance(material, dict)),
            *(
                (material, ".mp4" if material.get("type") == "video" else ".png")
                for material in videos
                if isinstance(material, dict)
            ),
        ]
        total = len(material_specs)
        for index, (material, suffix) in enumerate(material_specs, start=1):
            source = str(material.get("path") or "").strip()
            filename = f"{str(uuid.uuid4()).upper()}{suffix}"
            staging_path = staging_assets / filename
            _progress(progress, f"正在下载素材 {index}/{total}……")
            if material.get("local_id") and Path(source).is_file():
                shutil.copy2(source, staging_path)
            else:
                download(source, staging_path)
            material["path"] = str(final_asset_dir / filename)
            if material.get("local_id"):
                material["local_id"] = ""
            downloaded += 1

        max_end = 0
        for track in content.get("tracks") or []:
            for segment in track.get("segments") or []:
                target_range = segment.get("target_timerange") or {}
                max_end = max(
                    max_end,
                    int(target_range.get("start") or 0) + int(target_range.get("duration") or 0),
                )
        content["duration"] = max_end
        now_us = int(time.time() * 1_000_000)
        content["update_time"] = now_us
        meta = jianying._new_meta_template(normalized, normalized, target_dir, root)
        meta["tm_duration"] = max_end
        meta["draft_timeline_materials_size_"] = sum(
            len(track.get("segments") or []) for track in content.get("tracks") or []
        )

        compact_content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        jianying._write_json(staging / "draft_content.json", content)
        jianying._write_json(staging / "draft_info.json", content)
        jianying._write_json(staging / f"{asset_group}.json", content)
        jianying._write_json(staging / "template-2.tmp", {"draft_content": compact_content})
        template_content = copy.deepcopy(content)
        template_content["id"] = str(uuid.uuid4()).upper()
        jianying._write_json(staging / "template.tmp", template_content)
        jianying._write_json(staging / "draft_meta_info.json", meta)
        jianying._write_json(staging / "attachment_pc_common.json", {"pc_feature_flag": 0, "template_item_infos": [], "unlock_template_ids": []})
        jianying._write_json(staging / "draft_agency_config.json", {"marterials": None, "use_converter": False, "video_resolution": 720})
        jianying._write_json(staging / "mihe_server_draft.json", raw_payload)
        staging.replace(target_dir)

    jianying._register_root_meta(meta, target_dir / "draft_content.json")
    tracks = content.get("tracks") or []
    report = {
        "draft_id": normalized,
        "draft_name": normalized,
        "draft_dir": str(target_dir),
        "already_imported": False,
        "verified": True,
        "track_count": len(tracks),
        "segment_count": sum(len(track.get("segments") or []) for track in tracks),
        "asset_count": downloaded,
        "server_json_path": str(target_dir / "mihe_server_draft.json"),
        "method": "mihe_direct_http",
        "warnings": [],
        "message": "ok",
    }
    _progress(progress, f"米核草稿已直接导入：{normalized}")
    return report
