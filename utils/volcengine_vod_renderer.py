#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render ``jianying_draft_key`` payloads with Volcengine VOD cloud editing.

The local draft key is intentionally kept provider-neutral.  This module
resolves and uploads its media assets, translates the timeline to VOD's
``EditParam`` structure, submits ``SubmitDirectEditTaskAsync``, and queries the
result.  JianYing-only resources are mapped to VOD resources and reported in
``effect_replacements`` instead of being silently treated as identical.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict
from PIL import Image
from volcengine.ApiInfo import ApiInfo
from volcengine.const.Const import (
    CATEGORY_AUDIO,
    CATEGORY_IMAGE,
    FILE_TYPE_IMAGE,
    FILE_TYPE_MEDIA,
)
from volcengine.util.Functions import Function
from volcengine.vod.VodService import VodService
from volcengine.vod.models.request.request_vod_pb2 import (
    VodGetDirectEditProgressRequest,
    VodGetDirectEditResultRequest,
    VodSubmitDirectEditTaskAsyncRequest,
    VodUploadMaterialRequest,
)

from utils.draft_key_importer import KeyValidationError, _call_items, _validate_key


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = PROJECT_ROOT / "temp" / "vod_render_cache"
DOWNLOAD_DIR = CACHE_ROOT / "downloads"
MATERIAL_CACHE_PATH = CACHE_ROOT / "materials.json"
DEFAULT_TIMEOUT = 90


class VodConfigurationError(RuntimeError):
    """Raised when VOD credentials or the target space are not configured."""


class VodRenderError(RuntimeError):
    """Raised when a VOD upload, submission, or result query fails."""


@dataclass(frozen=True)
class VodConfig:
    access_key: str
    secret_key: str
    space_name: str
    region: str = "cn-north-1"

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "VodConfig":
        load_dotenv(env_path or PROJECT_ROOT / ".env", override=False)
        config = cls(
            access_key=os.getenv("VOLCENGINE_ACCESS_KEY", "").strip(),
            secret_key=os.getenv("VOLCENGINE_SECRET_KEY", "").strip(),
            space_name=os.getenv("VOD_SPACE_NAME", "").strip(),
            region=os.getenv("VOD_REGION", "cn-north-1").strip() or "cn-north-1",
        )
        missing = [
            name
            for name, value in (
                ("VOLCENGINE_ACCESS_KEY", config.access_key),
                ("VOLCENGINE_SECRET_KEY", config.secret_key),
                ("VOD_SPACE_NAME", config.space_name),
            )
            if not value
        ]
        if missing:
            raise VodConfigurationError("missing environment variables: " + ", ".join(missing))
        return config


@dataclass
class Material:
    source: str
    mid: str
    kind: str
    path: str
    width: int = 0
    height: int = 0
    duration_ms: int = 0


def _safe_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _ms(value: Any, default: int = 0) -> int:
    """Convert this project's microsecond timeline values to milliseconds."""
    try:
        return max(0, round(float(value) / 1000.0))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _offset_px(value: Any, canvas_dimension: int) -> float:
    """Accept either JianYing normalized offsets or UI pixel offsets."""
    raw = _float(value)
    return raw if abs(raw) > 3 else raw * canvas_dimension


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _response_json(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    if isinstance(value, dict):
        return value
    if hasattr(value, "DESCRIPTOR"):
        return MessageToDict(value, preserving_proto_field_name=False)
    raise VodRenderError(f"unexpected VOD response type: {type(value).__name__}")


def _response_error(payload: dict[str, Any]) -> tuple[str, str]:
    metadata = payload.get("ResponseMetadata") or {}
    error = metadata.get("Error") or {}
    return str(error.get("Code") or ""), str(error.get("Message") or "")


def _asset_target(item: dict[str, Any], kind: str) -> str:
    fields = ("audio_url", "url", "path", "file_path") if kind == "audio" else (
        "image_url",
        "img",
        "url",
        "path",
        "file_path",
    )
    for field in fields:
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return ""


def _resolve_asset(target: str, base_dir: Path) -> Path:
    parsed = urlparse(target)
    if parsed.scheme in ("http", "https"):
        suffix = Path(parsed.path).suffix[:12] or ".bin"
        path = DOWNLOAD_DIR / f"{hashlib.sha256(target.encode('utf-8')).hexdigest()}{suffix}"
        if path.exists() and path.stat().st_size > 0:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        with requests.get(target, stream=True, timeout=DEFAULT_TIMEOUT) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        if temporary.stat().st_size <= 0:
            raise VodRenderError(f"downloaded asset is empty: {target}")
        temporary.replace(path)
        return path

    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        local = (base_dir / candidate).resolve()
        root_fallback = (PROJECT_ROOT / candidate).resolve()
        candidate = local if local.exists() else root_fallback
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise VodRenderError(f"asset not found: {target}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _audio_duration_ms(path: Path) -> int:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as audio:
            return round(audio.getnframes() / audio.getframerate() * 1000)
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise VodRenderError(f"cannot probe audio duration: {path.name}")
    return max(1, round(float(completed.stdout.strip()) * 1000))


class VolcengineVodRenderer:
    def __init__(self, config: VodConfig | None = None):
        self.config = config or VodConfig.from_env()
        self.client = VodService(self.config.region)
        self.client.set_ak(self.config.access_key)
        self.client.set_sk(self.config.secret_key)
        self.client.api_info.setdefault(
            "GetEffectList",
            ApiInfo("POST", "/", {"Action": "GetEffectList", "Version": "2018-01-01"}, {}, {}),
        )
        self.client.api_info.setdefault(
            "MGetMaterial",
            ApiInfo("GET", "/", {"Action": "MGetMaterial", "Version": "2018-01-01"}, {}, {}),
        )
        self._effect_catalog: dict[str, list[dict[str, Any]]] | None = None

    def validate_space(self) -> dict[str, str]:
        from volcengine.vod.models.request.request_vod_pb2 import VodListSpaceRequest

        request = VodListSpaceRequest()
        response = _response_json(self.client.list_space(request))
        code, message = _response_error(response)
        if code:
            raise VodRenderError(f"ListSpace failed: {code}: {message}")
        result = response.get("Result") or []
        spaces = result if isinstance(result, list) else (result.get("SpaceList") or [])
        match = next((item for item in spaces if item.get("SpaceName") == self.config.space_name), None)
        if not match:
            raise VodRenderError(f"VOD space not found: {self.config.space_name}")
        return {
            "space_name": self.config.space_name,
            "region": str(match.get("Region") or self.config.region),
        }

    def get_effect_catalog(self, *, refresh: bool = False) -> dict[str, list[dict[str, Any]]]:
        if self._effect_catalog is not None and not refresh:
            return self._effect_catalog
        catalog: dict[str, list[dict[str, Any]]] = {}
        for panel in ("specialeffects", "effect", "flower", "transition"):
            response = _response_json(
                self.client.json("GetEffectList", {}, json.dumps({"Panel": panel}, ensure_ascii=False))
            )
            code, message = _response_error(response)
            if code:
                raise VodRenderError(f"GetEffectList({panel}) failed: {code}: {message}")
            catalog[panel] = list(((response.get("Result") or {}).get("Effects") or []))
        self._effect_catalog = catalog
        return catalog

    def _upload_material(self, path: Path, kind: str) -> Material:
        fingerprint = _sha256(path)
        cache = _load_json(MATERIAL_CACHE_PATH, {})
        cache_key = f"{self.config.space_name}:{kind}:{fingerprint}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("mid"):
            material = Material(**cached)
            # A direct-edit Source is a full TOS URI.  Older POC cache entries
            # used the material ID itself, which the render service interprets
            # as a bucket name.
            if material.source.count("/") < 3:
                material.source = self._material_source(material.mid)
                cache[cache_key] = material.__dict__
                _atomic_json(MATERIAL_CACHE_PATH, cache)
            return material

        suffix = path.suffix.lower() or (".png" if kind == "image" else ".mp3")
        category = CATEGORY_IMAGE if kind == "image" else CATEGORY_AUDIO
        file_type = FILE_TYPE_IMAGE if kind == "image" else FILE_TYPE_MEDIA
        request = VodUploadMaterialRequest()
        request.SpaceName = self.config.space_name
        request.FilePath = str(path)
        request.FileType = file_type
        request.FileExtension = suffix
        request.CallbackArgs = ""
        request.Functions = json.dumps(
            [
                Function.get_meta_func(),
                Function.get_add_material_option_info_func(
                    title=f"draft-render-{path.stem[:50]}",
                    tags="draft-render",
                    description="Uploaded by the draft_key VOD renderer",
                    category=category,
                    record_type=2,
                    format_input=suffix.lstrip(".").upper(),
                ),
            ],
            ensure_ascii=False,
        )
        response = self.client.upload_material(request)
        error = response.ResponseMetadata.Error
        if error.Code:
            raise VodRenderError(f"material upload failed: {error.Code}: {error.Message}")
        mid = str(response.Result.Data.Mid or "")
        if not mid:
            raise VodRenderError(f"material upload returned no Mid: {path.name}")

        width = height = duration_ms = 0
        if kind == "image":
            width, height = _image_size(path)
        else:
            duration_ms = _audio_duration_ms(path)
        material = Material(
            source=self._material_source(mid),
            mid=mid,
            kind=kind,
            path=str(path),
            width=width,
            height=height,
            duration_ms=duration_ms,
        )
        cache[cache_key] = material.__dict__
        _atomic_json(MATERIAL_CACHE_PATH, cache)
        return material

    def _material_source(self, mid: str) -> str:
        response = _response_json(
            self.client.get(
                "MGetMaterial",
                {"Mid": mid, "Space": self.config.space_name, "Limit": 1, "Offset": 0},
            )
        )
        code, message = _response_error(response)
        if code:
            raise VodRenderError(f"MGetMaterial failed: {code}: {message}")
        infos = ((((response.get("Result") or {}).get("MaterialSet") or {}).get("MaterialInfos")) or [])
        basic = (infos[0].get("MaterialBasicInfo") or {}) if infos else {}
        store_uri = str(basic.get("StoreUri") or "").lstrip("/")
        if not store_uri:
            raise VodRenderError(f"MGetMaterial returned no StoreUri for {mid}")
        return f"tos://{store_uri}"

    def prepare_materials(self, key: dict[str, Any], base_dir: Path) -> dict[str, Material]:
        materials: dict[str, Material] = {}
        for call in key.get("calls", []):
            kind = "audio" if call.get("tool") == "add_audios" else "image" if call.get("tool") == "add_images" else ""
            if not kind:
                continue
            for item in _call_items(call):
                target = _asset_target(item, kind)
                if not target or target in materials:
                    continue
                path = _resolve_asset(target, base_dir)
                materials[target] = self._upload_material(path, kind)
        return materials

    @staticmethod
    def _find_effect(catalog: dict[str, list[dict[str, Any]]], panel: str, name: str) -> dict[str, Any] | None:
        return next((item for item in catalog.get(panel, []) if item.get("Name") == name), None)

    def _effect_plan(self, key: dict[str, Any]) -> tuple[dict[str, tuple[str, dict[str, Any]]], list[dict[str, str]]]:
        catalog = self.get_effect_catalog()
        available_filters = {str(item.get("Name")): item for item in catalog["effect"]}
        available_special = {str(item.get("Name")): item for item in catalog["specialeffects"]}
        requested = []
        for call in key.get("calls", []):
            if call.get("tool") == "add_effects":
                requested.extend(str(item.get("effect") or item.get("name") or "").strip() for item in _call_items(call))

        fallbacks = {
            "金粉闪闪": ("specialeffects", "镜像对称"),
            "柔光": ("effect", "午后"),
            "光晕": ("effect", "白皙"),
            "梦幻": ("effect", "Vintage"),
        }
        plan: dict[str, tuple[str, dict[str, Any]]] = {}
        replacements: list[dict[str, str]] = []
        for original in dict.fromkeys(name for name in requested if name):
            if original in available_special:
                panel, resource = "specialeffects", available_special[original]
            elif original in available_filters:
                panel, resource = "effect", available_filters[original]
            else:
                panel, replacement = fallbacks.get(original, ("effect", "清晰"))
                source_map = available_special if panel == "specialeffects" else available_filters
                resource = source_map.get(replacement) or next(iter(source_map.values()))
            plan[original] = (panel, resource)
            replacements.append(
                {
                    "original": original,
                    "vod_panel": panel,
                    "replacement": str(resource.get("Name") or ""),
                    "exact": str(resource.get("Name") or "") == original,
                }
            )
        return plan, replacements

    def build_edit_param(
        self,
        key: dict[str, Any],
        materials: dict[str, Material],
        *,
        output_name: str | None = None,
        include_text: bool = True,
        include_effects: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        errors = _validate_key(key)
        if errors:
            raise KeyValidationError(errors)
        draft = key.get("draft") or {}
        meta = key.get("meta") or {}
        canvas_width = int(draft.get("width") or 1920)
        canvas_height = int(draft.get("height") or 1080)
        title = output_name or str(meta.get("title") or draft.get("name") or "draft-render")
        title = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", title).strip("-") or "draft-render"

        effect_plan, replacements = self._effect_plan(key) if include_effects else ({}, [])
        tracks: list[list[dict[str, Any]]] = []
        segment_map: dict[tuple[str, int], dict[str, Any]] = {}
        skipped: list[dict[str, str]] = []

        for call_index, call in enumerate(key.get("calls", [])):
            tool = call.get("tool")
            call_id = str(call.get("call_id") or f"call_{call_index}")
            if tool == "add_keyframes":
                continue
            elements: list[dict[str, Any]] = []
            for item_index, item in enumerate(_call_items(call)):
                start_ms = _ms(item.get("start"))
                end_ms = max(start_ms + 1, _ms(item.get("end"), start_ms + 1))
                element_id = _safe_id(tool.replace("add_", ""))

                if tool in ("add_images", "add_audios"):
                    kind = "image" if tool == "add_images" else "audio"
                    target = _asset_target(item, kind)
                    material = materials.get(target)
                    if material is None:
                        raise VodRenderError(f"material not prepared: {target}")
                    if kind == "audio":
                        source_end = min(material.duration_ms, end_ms - start_ms) if material.duration_ms else end_ms - start_ms
                        element = {
                            "ID": element_id,
                            "Type": "audio",
                            "Source": material.source,
                            "TargetTime": [start_ms, end_ms],
                            "Extra": [
                                {"ID": _safe_id("trim"), "Type": "trim", "StartTime": 0, "EndTime": source_end},
                                {"ID": _safe_id("volume"), "Type": "a_volume", "Volume": _float(item.get("volume"), 1.0)},
                                {"ID": _safe_id("fade"), "Type": "a_fade", "FadeIn": 0, "FadeOut": 0},
                                {"ID": _safe_id("speed"), "Type": "speed", "Speed": 1},
                            ],
                            "UserData": {"id": element_id, "source": material.source, "type": "audio"},
                        }
                    else:
                        base_width = int(item.get("width") or material.width or canvas_width)
                        base_height = int(item.get("height") or material.height or canvas_height)
                        scale_x = _float(item.get("scale_x"), 1.0)
                        scale_y = _float(item.get("scale_y"), scale_x)
                        pos_x = round((canvas_width - base_width * scale_x) / 2 + _offset_px(item.get("transform_x"), canvas_width))
                        pos_y = round((canvas_height - base_height * scale_y) / 2 + _offset_px(item.get("transform_y"), canvas_height))
                        element = {
                            "ID": element_id,
                            "Type": "image",
                            "Source": material.source,
                            "TargetTime": [start_ms, end_ms],
                            "Extra": [
                                {
                                    "ID": _safe_id("transform"),
                                    "Type": "transform",
                                    "PosX": pos_x,
                                    "PosY": pos_y,
                                    "Width": base_width,
                                    "Height": base_height,
                                    "ScaleX": scale_x,
                                    "ScaleY": scale_y,
                                    "Rotation": _float(item.get("rotation")),
                                    "FlipX": False,
                                    "FlipY": False,
                                    "Alpha": _float(item.get("alpha"), 1.0),
                                },
                                {
                                    "ID": _safe_id("equalizer"),
                                    "Type": "equalizer",
                                    "Contrast": 0,
                                    "Tone": 0,
                                    "Saturation": 0,
                                    "Temperature": 0,
                                    "Brightness": 0,
                                    "TargetTime": [0, end_ms - start_ms],
                                },
                            ],
                            "UserData": {"id": element_id, "source": material.source, "type": "image"},
                        }
                    segment_map[(call_id, item_index)] = element
                    elements.append(element)
                    continue

                if tool == "add_captions":
                    text = str(item.get("text") or "")
                    if not include_text or not text.strip():
                        continue
                    font_size = max(12, int(_float(item.get("font_size"), 72)))
                    text_width = min(canvas_width * 0.88, max(font_size * 2, len(text) * font_size))
                    pos_x = round((canvas_width - text_width) / 2 + _offset_px(item.get("transform_x"), canvas_width))
                    pos_y = round(canvas_height * 0.78 - font_size / 2 + _offset_px(item.get("transform_y"), canvas_height))
                    elements.append(
                        {
                            "ID": element_id,
                            "Type": "text",
                            "TargetTime": [start_ms, end_ms],
                            "Text": text,
                            "FontSize": font_size,
                            "FontColor": str(item.get("font_color") or "#FFFFFFFF"),
                            "ShadowColor": "#00000088",
                            "AlignType": 1,
                            "LineMaxWidth": 0.88,
                            "Extra": [
                                {
                                    "ID": _safe_id("transform"),
                                    "Type": "transform",
                                    "PosX": pos_x,
                                    "PosY": pos_y,
                                    "Width": round(text_width),
                                    "Height": round(font_size * 1.5),
                                    "Rotation": 0,
                                    "FlipX": False,
                                    "FlipY": False,
                                    "Alpha": _float(item.get("alpha"), 1.0),
                                }
                            ],
                            "UserData": {
                                "id": element_id,
                                "source": "",
                                "type": "text",
                                "textType": "basic",
                            },
                        }
                    )
                    continue

                if tool == "add_effects":
                    if not include_effects:
                        continue
                    original = str(item.get("effect") or item.get("name") or "").strip()
                    mapped = effect_plan.get(original)
                    if not mapped:
                        skipped.append({"type": "effect", "name": original})
                        continue
                    panel, resource = mapped
                    filter_type = "effect_filter" if panel == "specialeffects" else "lut_filter"
                    file_urls = ((resource.get("FileUrl") or {}).get("UrlList") or [])
                    source = str((file_urls[0] if file_urls else "") or resource.get("Id") or "")
                    elements.append(
                        {
                            "ID": element_id,
                            "Type": "effect",
                            "TargetTime": [start_ms, end_ms],
                            "Extra": [
                                {
                                    "ID": _safe_id("effect"),
                                    "Type": filter_type,
                                    "TargetTime": [0, end_ms - start_ms],
                                    "Source": source,
                                    "UserData": {
                                        "type": filter_type,
                                        "source": source,
                                        "name": resource.get("Name"),
                                    },
                                }
                            ],
                            "UserData": {
                                "id": element_id,
                                "name": resource.get("Name"),
                                "source": source,
                                "type": "effect",
                                "subType": "specialEffect" if panel == "specialeffects" else "filter",
                            },
                        }
                    )
            if elements:
                tracks.append(elements)

        # VOD's public effect inventory does not expose JianYing keyframe IDs.
        # Preserve their final values as the closest deterministic static pose.
        applied_keyframes = 0
        for call in key.get("calls", []):
            if call.get("tool") != "add_keyframes":
                continue
            grouped: dict[tuple[str, int, str], dict[str, Any]] = {}
            for frame in _call_items(call):
                ref = frame.get("segment_ref") or {}
                group_key = (str(ref.get("call_id") or ""), int(ref.get("index") or 0), str(frame.get("property") or ""))
                current = grouped.get(group_key)
                if current is None or _ms(frame.get("offset")) >= _ms(current.get("offset")):
                    grouped[group_key] = frame
            for (ref_id, ref_index, prop), frame in grouped.items():
                element = segment_map.get((ref_id, ref_index))
                if not element:
                    continue
                transform = next((extra for extra in element.get("Extra", []) if extra.get("Type") == "transform"), None)
                if not transform:
                    continue
                value = _float(frame.get("value"))
                if prop in ("UNIFORM_SCALE", "KFTypeUniformScale"):
                    transform["ScaleX"] = transform["ScaleY"] = value
                elif prop == "KFTypePositionX":
                    transform["PosX"] = round((canvas_width - transform["Width"] * transform.get("ScaleX", 1)) / 2 + value * canvas_width)
                elif prop == "KFTypePositionY":
                    transform["PosY"] = round((canvas_height - transform["Height"] * transform.get("ScaleY", 1)) / 2 + value * canvas_height)
                elif prop == "KFTypeAlpha":
                    transform["Alpha"] = value
                else:
                    continue
                applied_keyframes += 1

        task_token = uuid.uuid4().hex[:12]
        edit_param = {
            "Canvas": {"Width": canvas_width, "Height": canvas_height, "BackgroundColor": "#000000FF"},
            "Output": {
                "Fps": 30,
                "Format": "mp4",
                "DisableVideo": False,
                "DisableAudio": False,
                "Codec": {
                    "VideoCodec": "h264",
                    "AudioCodec": "aac",
                    "AudioBitrate": 128,
                    "Crf": 23,
                },
            },
            "Upload": {
                "SpaceName": self.config.space_name,
                "VideoName": title,
                "FileName": f"draft-render/{title}-{task_token}.mp4",
            },
            "Uploader": self.config.space_name,
            "Track": tracks,
        }
        report = {
            "track_count": len(tracks),
            "element_count": sum(len(track) for track in tracks),
            "material_count": len(materials),
            "effect_replacements": replacements,
            "keyframes_applied_as_static_pose": applied_keyframes,
            "skipped": skipped,
        }
        return edit_param, report

    def submit(self, edit_param: dict[str, Any]) -> dict[str, Any]:
        request = VodSubmitDirectEditTaskAsyncRequest()
        request.Uploader = self.config.space_name
        request.Application = "VideoTrackToB"
        request.EditParam = json.dumps(
            edit_param, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        response = _response_json(self.client.submit_direct_edit_task_async(request))
        code, message = _response_error(response)
        if code:
            raise VodRenderError(f"SubmitDirectEditTaskAsync failed: {code}: {message}")
        req_id = str((response.get("Result") or {}).get("ReqId") or "")
        if not req_id:
            raise VodRenderError("SubmitDirectEditTaskAsync returned no ReqId")
        return {"req_id": req_id, "response": response}

    def get_progress(self, req_id: str) -> dict[str, Any]:
        request = VodGetDirectEditProgressRequest()
        request.ReqId = req_id
        response = _response_json(self.client.get_direct_edit_progress(request))
        code, message = _response_error(response)
        if code:
            raise VodRenderError(f"GetDirectEditProgress failed: {code}: {message}")
        return response

    def get_result(self, req_ids: list[str] | str) -> dict[str, Any]:
        request = VodGetDirectEditResultRequest()
        request.ReqIds.extend([req_ids] if isinstance(req_ids, str) else req_ids)
        response = _response_json(self.client.get_direct_edit_result(request))
        code, message = _response_error(response)
        if code:
            raise VodRenderError(f"GetDirectEditResult failed: {code}: {message}")
        return response

    def get_media_info(self, vid: str) -> dict[str, Any]:
        from volcengine.vod.models.request.request_vod_pb2 import VodGetMediaInfosRequest

        request = VodGetMediaInfosRequest()
        request.Vids = vid
        response = _response_json(self.client.get_media_infos(request))
        code, message = _response_error(response)
        if code:
            raise VodRenderError(f"GetMediaInfos failed: {code}: {message}")
        media = ((response.get("Result") or {}).get("MediaInfoList") or [])
        return media[0] if media else {}

    def wait_for_result(self, req_id: str, *, timeout: int = 900, interval: int = 8) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_progress: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last_progress = self.get_progress(req_id)
            result = self.get_result(req_id)
            raw_result = result.get("Result") or []
            details = raw_result if isinstance(raw_result, list) else (raw_result.get("EditTaskInfo") or [])
            if details:
                status = str(details[0].get("Status") or details[0].get("State") or "").lower()
                if status in {
                    "success",
                    "succeeded",
                    "finished",
                    "done",
                    "failed",
                    "failed_run",
                    "error",
                }:
                    return result
                if details[0].get("Output") or details[0].get("Vid"):
                    return result
            time.sleep(max(1, interval))
        raise TimeoutError(f"VOD edit task did not finish within {timeout}s; last progress={last_progress}")


def render_draft_key_vod(
    key: dict[str, Any],
    *,
    base_dir: Path,
    submit: bool = True,
    wait: bool = False,
    include_text: bool = True,
    include_effects: bool = True,
) -> dict[str, Any]:
    renderer = VolcengineVodRenderer()
    space = renderer.validate_space()
    materials = renderer.prepare_materials(key, base_dir)
    edit_param, report = renderer.build_edit_param(
        key,
        materials,
        include_text=include_text,
        include_effects=include_effects,
    )
    payload: dict[str, Any] = {
        "success": True,
        "space": space,
        "edit_param": edit_param,
        "conversion": report,
    }
    if not submit:
        payload["submitted"] = False
        return payload
    submitted = renderer.submit(edit_param)
    payload.update({"submitted": True, "req_id": submitted["req_id"]})
    if wait:
        payload["result"] = renderer.wait_for_result(submitted["req_id"])
    return payload
