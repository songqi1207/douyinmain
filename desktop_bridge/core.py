#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless core for the Windows JianYing draft bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import utils.draft_key_importer as draft_importer
from utils.draft_key_importer import AssetDownloadError, KeyValidationError


ProgressCallback = Callable[[str], None]


class BridgeError(RuntimeError):
    pass


def _progress(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)


def _decode_json_string(value: str) -> Any:
    raw = value.strip().lstrip("\ufeff")
    if not raw:
        raise BridgeError("JSON 内容为空")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}") from exc


def extract_draft_key(payload: Any) -> dict[str, Any]:
    """Extract a draft key from direct JSON or common Coze result wrappers."""
    if isinstance(payload, str):
        return extract_draft_key(_decode_json_string(payload))
    if not isinstance(payload, dict):
        raise BridgeError("运行结果必须是 JSON 对象")
    if isinstance(payload.get("calls"), list) and payload.get("calls"):
        return payload

    preferred_keys = (
        "draft_key",
        "key",
        "key_json",
        "output",
        "result",
        "data",
        "body",
    )
    for field in preferred_keys:
        value = payload.get(field)
        if value in (None, "", [], {}):
            continue
        try:
            return extract_draft_key(value)
        except BridgeError:
            continue

    # Coze sometimes nests named outputs under one additional dictionary.
    for value in payload.values():
        if not isinstance(value, (dict, str)):
            continue
        try:
            return extract_draft_key(value)
        except BridgeError:
            continue
    raise BridgeError("没有找到 draft_key；请粘贴扣子 End 节点返回的 draft_key JSON")


def load_payload_file(path: Path | str) -> Any:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise BridgeError(f"JSON 文件不存在：{source}")
    key = extract_draft_key(_decode_json_string(source.read_text(encoding="utf-8-sig")))
    for call in key.get("calls") or []:
        params = call.get("params") or {}
        for value in params.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                for field in ("audio_url", "image_url", "img", "url", "path", "file_path"):
                    raw = str(item.get(field) or "").strip()
                    if not raw or "://" in raw or Path(raw).is_absolute():
                        continue
                    candidate = (source.parent / raw).resolve()
                    if candidate.exists():
                        item[field] = str(candidate)
    return key


def _configure_frozen_state() -> None:
    """Keep cache and idempotency state outside PyInstaller's temp directory."""
    configured = os.getenv("DRAFT_BRIDGE_STATE_DIR", "").strip()
    if not configured and not getattr(sys, "frozen", False):
        return
    base = Path(configured).expanduser() if configured else Path(os.getenv("APPDATA") or Path.home()) / "DouyinDraftBridge" / "data"
    base.mkdir(parents=True, exist_ok=True)
    draft_importer._CACHE_DIR = base / "draft_key_cache"
    draft_importer._REGISTRY_PATH = base / "draft_key_imports.json"
    draft_importer._RENDER_KEYS_DIR = base / "draft_render_keys"


def detect_draft_roots() -> list[Path]:
    candidates: list[Path] = []
    configured = os.getenv("JIANYING_DRAFT_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        root = Path(local_appdata)
        candidates.extend(
            [
                root / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft",
                root / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            ]
        )
    result: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and resolved not in result:
            result.append(resolved)
    return result


def _registry_install_locations() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    locations: list[Path] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    branches = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for root in roots:
        for branch in branches:
            try:
                parent = winreg.OpenKey(root, branch)
            except OSError:
                continue
            with parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        child_name = winreg.EnumKey(parent, index)
                        child = winreg.OpenKey(parent, child_name)
                    except OSError:
                        continue
                    with child:
                        try:
                            display_name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                        except OSError:
                            display_name = ""
                        if not any(token in display_name.lower() for token in ("剪映", "jianying", "capcut")):
                            continue
                        for value_name in ("InstallLocation", "DisplayIcon"):
                            try:
                                raw = str(winreg.QueryValueEx(child, value_name)[0]).strip(' "')
                            except OSError:
                                continue
                            if raw:
                                locations.append(Path(raw.split(",", 1)[0]))
    return locations


def detect_jianying_executables() -> list[Path]:
    candidates: list[Path] = []
    configured = os.getenv("JIANYING_EXE", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    program_files = [os.getenv("PROGRAMFILES", ""), os.getenv("PROGRAMFILES(X86)", "")]
    if local_appdata:
        root = Path(local_appdata)
        candidates.extend(
            [
                root / "JianyingPro" / "Apps" / "JianyingPro.exe",
                root / "JianyingPro" / "JianyingPro.exe",
                root / "CapCut" / "Apps" / "CapCut.exe",
                root / "CapCut" / "CapCut.exe",
            ]
        )
        for pattern in (
            "JianyingPro/Apps/*/JianyingPro.exe",
            "CapCut/Apps/*/CapCut.exe",
        ):
            candidates.extend(root.glob(pattern))
    for program_root in filter(None, program_files):
        root = Path(program_root)
        candidates.extend([root / "JianyingPro" / "JianyingPro.exe", root / "CapCut" / "CapCut.exe"])
    for location in _registry_install_locations():
        if location.suffix.lower() == ".exe":
            candidates.append(location)
        else:
            candidates.extend([location / "JianyingPro.exe", location / "CapCut.exe"])
    result: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.suffix.lower() == ".exe" and resolved not in result:
            result.append(resolved)
    return result


def validate_draft_root(path: Path | str) -> Path:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise BridgeError(f"草稿目录不可用：{root}")
    return root


def validate_import_report(report: dict[str, Any]) -> dict[str, Any]:
    draft_dir = Path(str(report.get("draft_dir") or ""))
    required = ("draft_content.json", "draft_meta_info.json")
    missing = [name for name in required if not (draft_dir / name).is_file()]
    if missing:
        raise BridgeError("草稿写入不完整，缺少：" + "、".join(missing))
    content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    report = dict(report)
    report["verified"] = True
    report["track_count"] = len(content.get("tracks") or [])
    report["segment_count"] = sum(len(track.get("segments") or []) for track in content.get("tracks") or [])
    return report


def import_draft_payload(
    payload: Any,
    *,
    draft_root: Path | str,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    key = extract_draft_key(payload)
    root = validate_draft_root(draft_root)
    _configure_frozen_state()
    _progress(progress, "已识别 draft_key，正在校验和下载素材……")
    previous = os.environ.get("JIANYING_DRAFT_ROOT")
    os.environ["JIANYING_DRAFT_ROOT"] = str(root)
    try:
        report = draft_importer.import_draft_key(key, force=force, dry_run=False)
    except KeyValidationError as exc:
        raise BridgeError("draft_key 校验失败：" + "；".join(exc.errors)) from exc
    except AssetDownloadError as exc:
        detail = "；".join(f"{url}: {reason}" for url, reason in exc.failed.items())
        raise BridgeError("素材下载失败：" + detail) from exc
    except Exception as exc:
        raise BridgeError(f"草稿导入失败：{exc}") from exc
    finally:
        if previous is None:
            os.environ.pop("JIANYING_DRAFT_ROOT", None)
        else:
            os.environ["JIANYING_DRAFT_ROOT"] = previous
    _progress(progress, "草稿已写入，正在验证文件结构……")
    verified = validate_import_report(report)
    _progress(progress, f"导入成功：{verified.get('draft_name') or verified.get('draft_id')}")
    return verified


def open_directory(path: Path | str) -> None:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise BridgeError(f"目录不存在：{target}")
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(target)])


def launch_jianying(executable: Path | str) -> None:
    target = Path(executable).expanduser().resolve()
    if not target.is_file():
        raise BridgeError(f"剪映程序不存在：{target}")
    subprocess.Popen([str(target)], cwd=str(target.parent))
