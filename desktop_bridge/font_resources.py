"""Prepare and verify the Jianying fonts required by production workflows.

Jianying cloud fonts are downloaded by Jianying itself when a draft referencing
the resource is opened.  This module deliberately does not fetch proprietary
font files from third-party URLs.  It creates a small preload draft, discovers
the files written to Jianying's official cache, and binds those local paths back
into generated drafts so Jianying cannot silently substitute another font.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


REQUIRED_WORKFLOW_FONTS: tuple[dict[str, Any], ...] = (
    {
        "name": "出云龙",
        "resource_id": "7618137748045696292",
        "workflows": ("神",),
    },
    {
        "name": "江湖体",
        "resource_id": "7080097079397192228",
        "workflows": ("神",),
    },
    {
        "name": "毛笔行楷",
        "resource_id": "6912033793700270606",
        "workflows": ("书单", "香烟"),
        "aliases": ("华文行楷",),
    },
    {
        "name": "思源粗宋",
        "resource_id": "6807742980271641102",
        "workflows": ("书单",),
    },
    {
        "name": "高字标志黑",
        "resource_id": "7268259518427959866",
        "workflows": ("书单",),
    },
)

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}
_FONT_SIGNATURES = (
    b"\x00\x01\x00\x00",
    b"OTTO",
    b"ttcf",
    b"true",
    b"typ1",
    b"wOFF",
    b"wOF2",
)


def required_font_resources() -> list[dict[str, Any]]:
    """Return a caller-safe copy of the production font catalogue."""
    return [
        {
            **item,
            "workflows": list(item.get("workflows") or ()),
            "aliases": list(item.get("aliases") or ()),
        }
        for item in REQUIRED_WORKFLOW_FONTS
    ]


def jianying_font_cache_roots(draft_root: Path | str = "") -> list[Path]:
    """Return the official Jianying/CapCut cloud-effect cache directories."""
    candidates: list[Path] = []
    raw_draft_root = str(draft_root or "").strip()
    if raw_draft_root:
        root = Path(raw_draft_root).expanduser().resolve()
        # .../User Data/Projects/com.lveditor.draft -> .../User Data/Cache/effect
        if root.parent.name.lower() == "projects":
            candidates.append(root.parent.parent / "Cache" / "effect")

    local_appdata = str(os.getenv("LOCALAPPDATA") or "").strip()
    if local_appdata:
        base = Path(local_appdata).expanduser()
        candidates.extend(
            [
                base / "JianyingPro" / "User Data" / "Cache" / "effect",
                base / "CapCut" / "User Data" / "Cache" / "effect",
            ]
        )

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(str(candidate.resolve()))
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(candidate.resolve())
    return result


def _looks_like_font_file(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 1024:
            return False
        if path.suffix.lower() in _FONT_SUFFIXES:
            return True
        with path.open("rb") as handle:
            signature = handle.read(4)
        return signature in _FONT_SIGNATURES
    except OSError:
        return False


def find_cached_font(
    resource_id: str,
    *,
    cache_roots: Iterable[Path | str] | None = None,
    draft_root: Path | str = "",
) -> Path | None:
    """Locate one downloaded font file by Jianying resource ID."""
    normalized_id = str(resource_id or "").strip()
    if not normalized_id:
        return None
    roots = (
        [Path(item).expanduser().resolve() for item in cache_roots]
        if cache_roots is not None
        else jianying_font_cache_roots(draft_root)
    )
    for root in roots:
        resource_dir = root / normalized_id
        if not resource_dir.is_dir():
            continue
        try:
            candidates = sorted(
                (path for path in resource_dir.rglob("*") if path.is_file()),
                key=lambda path: (
                    path.suffix.lower() not in _FONT_SUFFIXES,
                    -path.stat().st_size,
                ),
            )
        except OSError:
            continue
        for candidate in candidates:
            if _looks_like_font_file(candidate):
                return candidate.resolve()
    return None


def _existing_font_path(value: Any, draft_dir: Path) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("file:"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path or "")
        if parsed.netloc:
            raw = f"//{parsed.netloc}{raw}"
        elif os.name == "nt" and len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = draft_dir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    return resolved if _looks_like_font_file(resolved) else None


def find_bound_font(
    resource_id: str,
    *,
    name: str = "",
    aliases: Iterable[str] | None = None,
    draft_dir: Path | str = "",
) -> Path | None:
    """Locate a font path Jianying has already bound into this draft.

    Jianying 11 may store downloaded fonts outside the legacy
    ``Cache/effect/<resource-id>`` layout. After a user downloads a font in the
    editor, the authoritative local path is written into ``draft_content.json``.
    """
    target_dir = Path(draft_dir).expanduser().resolve() if str(draft_dir).strip() else None
    if target_dir is None:
        return None
    content_path = target_dir / "draft_content.json"
    if not content_path.is_file():
        return None
    try:
        content = json.loads(content_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    expected_id = str(resource_id or "").strip()
    expected_names = {
        str(item or "").strip().casefold()
        for item in [name, *(aliases or [])]
        if str(item or "").strip()
    }

    def matches(candidate_id: Any, candidate_name: Any) -> bool:
        normalized_id = str(candidate_id or "").strip()
        normalized_name = str(candidate_name or "").strip().casefold()
        return bool(
            (expected_id and normalized_id == expected_id)
            or (expected_names and normalized_name in expected_names)
        )

    for material in (content.get("materials") or {}).get("texts") or []:
        if not isinstance(material, dict):
            continue
        material_name = material.get("font_name") or material.get("font_title")
        if matches(material.get("font_resource_id"), material_name):
            available = _existing_font_path(material.get("font_path"), target_dir)
            if available:
                return available

        for font in material.get("fonts") or []:
            if not isinstance(font, dict):
                continue
            font_id = font.get("resource_id") or font.get("effect_id") or font.get("id")
            font_name = font.get("title") or font.get("name") or material_name
            if matches(font_id, font_name):
                available = _existing_font_path(font.get("path"), target_dir)
                if available:
                    return available

        try:
            text_content = json.loads(str(material.get("content") or "{}"))
        except json.JSONDecodeError:
            continue
        for style in text_content.get("styles") or []:
            if not isinstance(style, dict):
                continue
            font = style.get("font") or {}
            if not isinstance(font, dict):
                continue
            if matches(font.get("id") or font.get("resource_id"), material_name):
                available = _existing_font_path(font.get("path"), target_dir)
                if available:
                    return available
    return None


def inspect_font_resources(
    resources: Iterable[dict[str, Any]] | None = None,
    *,
    draft_root: Path | str = "",
    draft_dir: Path | str = "",
    cache_roots: Iterable[Path | str] | None = None,
) -> list[dict[str, Any]]:
    """Report whether every requested cloud font exists in Jianying's cache."""
    selected = list(resources) if resources is not None else required_font_resources()
    statuses: list[dict[str, Any]] = []
    for resource in selected:
        resource_id = str(resource.get("resource_id") or "").strip()
        name = str(resource.get("name") or resource_id).strip()
        cached = find_cached_font(
            resource_id,
            cache_roots=cache_roots,
            draft_root=draft_root,
        )
        bound = None if cached else find_bound_font(
            resource_id,
            name=name,
            aliases=resource.get("aliases") or [],
            draft_dir=draft_dir,
        )
        available_path = cached or bound
        statuses.append(
            {
                **resource,
                "name": name,
                "resource_id": resource_id,
                "available": available_path is not None,
                "cached_path": str(available_path or ""),
                "source": "legacy_cache" if cached else ("draft_binding" if bound else ""),
            }
        )
    return statuses


def font_resources_from_import_report(report: dict[str, Any]) -> list[dict[str, str]]:
    """Extract unique font resources from a verified draft import report."""
    resources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in report.get("cloud_resources") or []:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "font":
            continue
        resource_id = str(item.get("resource_id") or "").strip()
        if not resource_id or resource_id in seen:
            continue
        seen.add(resource_id)
        resources.append(
            {
                "name": str(item.get("name") or resource_id).strip(),
                "resource_id": resource_id,
            }
        )
    return resources


def build_font_preload_key(
    resources: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a tiny draft that asks Jianying to download every required font."""
    selected = list(resources) if resources is not None else required_font_resources()
    calls: list[dict[str, Any]] = []
    for index, resource in enumerate(selected):
        name = str(resource.get("name") or "").strip()
        resource_id = str(resource.get("resource_id") or "").strip()
        if not name or not resource_id:
            continue
        calls.append(
            {
                "call_id": f"font_{index:02d}",
                "tool": "add_captions",
                "params": {
                    "captions": [
                        {
                            "text": f"{name}：天地玄黄 神话人物",
                            "start": index * 1_500_000,
                            "end": (index + 1) * 1_500_000,
                        }
                    ],
                    "font": name,
                    "font_resource_id": resource_id,
                    "font_size": 18,
                    "text_color": "#FFFFFF",
                    "border_color": "#000000",
                },
            }
        )
    if not calls:
        raise ValueError("没有可准备的字体资源")
    return {
        "schema_version": "1.0",
        "kind": "jianying_draft_key",
        "meta": {
            "workflow": "AI视频创作助手字体准备",
            "run_id": "font_preload_" + uuid.uuid4().hex,
            "title": "工作流字体准备",
        },
        "draft": {
            "width": 1080,
            "height": 1920,
            "name": "AI助手_工作流字体准备",
        },
        "calls": calls,
    }


def bind_cached_fonts(
    draft_dir: Path | str,
    resources: Iterable[dict[str, Any]],
    *,
    draft_root: Path | str = "",
    cache_roots: Iterable[Path | str] | None = None,
) -> dict[str, Any]:
    """Bind downloaded cache files into a plaintext Jianying draft.

    Returns missing names instead of allowing Jianying to fall back silently.
    """
    target_dir = Path(draft_dir).expanduser().resolve()
    content_path = target_dir / "draft_content.json"
    if not content_path.is_file():
        return {
            "bound": [],
            "missing": [str(item.get("name") or item.get("resource_id") or "") for item in resources],
            "encrypted_or_missing_draft": True,
        }

    try:
        content = json.loads(content_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "bound": [],
            "missing": [str(item.get("name") or item.get("resource_id") or "") for item in resources],
            "encrypted_or_missing_draft": True,
        }

    resource_paths: dict[str, tuple[str, str]] = {}
    missing: list[str] = []
    for resource in resources:
        resource_id = str(resource.get("resource_id") or "").strip()
        name = str(resource.get("name") or resource_id).strip()
        cached = find_cached_font(
            resource_id,
            cache_roots=cache_roots,
            draft_root=draft_root,
        )
        if cached is None:
            cached = find_bound_font(
                resource_id,
                name=name,
                aliases=resource.get("aliases") or [],
                draft_dir=target_dir,
            )
        if cached is None:
            missing.append(name)
            continue
        resource_paths[resource_id] = (name, str(cached))

    bound: set[str] = set()
    for material in (content.get("materials") or {}).get("texts") or []:
        if not isinstance(material, dict):
            continue
        try:
            text_content = json.loads(str(material.get("content") or "{}"))
        except json.JSONDecodeError:
            continue
        styles = text_content.get("styles") or []
        changed = False
        for style in styles:
            if not isinstance(style, dict):
                continue
            font = style.get("font") or {}
            resource_id = str(font.get("id") or "").strip()
            if resource_id not in resource_paths:
                continue
            name, cached_path = resource_paths[resource_id]
            style["font"] = {"id": resource_id, "path": cached_path}
            material["font_name"] = name
            material["font_path"] = cached_path
            material["font_resource_id"] = resource_id
            material["font_source_platform"] = 1
            material["font_title"] = name
            material["fonts"] = [
                {
                    "category_id": "",
                    "category_name": "",
                    "effect_id": resource_id,
                    "file_uri": "",
                    "id": str(uuid.uuid4()).upper(),
                    "path": cached_path,
                    "request_id": "",
                    "resource_id": resource_id,
                    "source_platform": 1,
                    "team_id": "",
                    "third_resource_id": "",
                    "title": name,
                }
            ]
            bound.add(name)
            changed = True
        if changed:
            material["content"] = json.dumps(
                text_content,
                ensure_ascii=False,
                separators=(",", ":"),
            )

    if bound:
        temporary = content_path.with_suffix(".json.fonts.tmp")
        temporary.write_text(
            json.dumps(content, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(content_path)

    return {
        "bound": sorted(bound),
        "missing": sorted(set(missing)),
        "encrypted_or_missing_draft": False,
        "updated_at": time.time(),
    }
