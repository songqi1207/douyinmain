#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless core for the Windows JianYing draft bridge."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

import requests
import utils.draft_key_importer as draft_importer
from desktop_bridge.mihe_direct import (
    export_mihe_server_draft_json,
    import_mihe_server_draft,
    validate_mihe_server_draft_id,
)
from utils.draft_key_importer import AssetDownloadError, KeyValidationError


ProgressCallback = Callable[[str], None]
DownloadCallback = Callable[[str, Path], None]

MIHE_SYNC_DOWNLOAD_URL = "https://cdn.miheai.com/tool/miheai.zip"
MIHE_SYNC_ARCHIVE_SHA256 = "F9328C434E6DBF5851C82DB92BA97683EED193B76C1806629377829D7C7986C4"
MIHE_SYNC_EXE_SHA256 = "1180A769301B87E5CD57941E2822E677AA6472E989EC7ED4DE04C36CDAD50CAB"
MIHE_SYNC_EXE_NAME = "米核剪映小助手.exe"


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


def _validate_mihe_draft_id(value: str) -> str:
    draft_id = value.strip().strip('"').strip("'")
    if len(draft_id) < 8 or len(draft_id) > 2048:
        raise BridgeError("米核草稿 ID 长度不正确")
    if any(character.isspace() or ord(character) < 32 for character in draft_id):
        raise BridgeError("米核草稿 ID 不能包含空格或换行")
    return draft_id


def extract_mihe_draft_id(payload: Any) -> str:
    """Extract the server-side draft ID returned by the legacy Coze plugin."""
    if isinstance(payload, str):
        raw = payload.strip().lstrip("\ufeff")
        if raw.startswith(("{", "[", '"')):
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                return _validate_mihe_draft_id(raw)
            return extract_mihe_draft_id(decoded)
        return _validate_mihe_draft_id(raw)
    if not isinstance(payload, dict):
        raise BridgeError("米核运行结果必须是草稿 ID 或 JSON 对象")
    for field in ("draft_id", "ids", "draft_url", "output", "result", "data", "body"):
        value = payload.get(field)
        if value in (None, "", [], {}):
            continue
        try:
            return extract_mihe_draft_id(value)
        except BridgeError:
            continue
    for value in payload.values():
        if not isinstance(value, (dict, str)):
            continue
        try:
            return extract_mihe_draft_id(value)
        except BridgeError:
            continue
    raise BridgeError("没有找到米核 draft_id；请粘贴扣子结束节点返回的草稿 ID")


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


def mihe_sync_directory() -> Path:
    configured = os.getenv("DRAFT_BRIDGE_MIHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(os.getenv("APPDATA") or Path.home()) / "DouyinDraftBridge" / "mihe").resolve()


def mihe_sync_executable_path() -> Path:
    return mihe_sync_directory() / MIHE_SYNC_EXE_NAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _download_file(url: str, destination: Path) -> None:
    with requests.get(url, stream=True, timeout=(15, 180)) as response:
        response.raise_for_status()
        with destination.open("wb") as stream:
            for block in response.iter_content(chunk_size=1024 * 1024):
                if block:
                    stream.write(block)


def ensure_mihe_sync(
    *,
    progress: ProgressCallback | None = None,
    base_dir: Path | str | None = None,
    download_url: str = MIHE_SYNC_DOWNLOAD_URL,
    archive_sha256: str = MIHE_SYNC_ARCHIVE_SHA256,
    executable_sha256: str = MIHE_SYNC_EXE_SHA256,
    downloader: DownloadCallback | None = None,
) -> Path:
    """Install the pinned official Mihe portable sync client on first use.

    The third-party executable is deliberately not embedded in our GitHub
    binary. It is fetched from Mihe's official CDN and accepted only when both
    the archive and portable executable match the reviewed hashes.
    """
    root = Path(base_dir).expanduser().resolve() if base_dir else mihe_sync_directory()
    root.mkdir(parents=True, exist_ok=True)
    target = root / MIHE_SYNC_EXE_NAME
    if target.is_file() and _sha256(target) == executable_sha256.upper():
        _progress(progress, "已找到经过校验的米核同步器")
        return target

    archive_path = root / "miheai.zip.download"
    executable_temp = root / f"{MIHE_SYNC_EXE_NAME}.download"
    for temporary in (archive_path, executable_temp):
        temporary.unlink(missing_ok=True)

    _progress(progress, "正在从米核官方地址下载同步器……")
    try:
        (downloader or _download_file)(download_url, archive_path)
        if _sha256(archive_path) != archive_sha256.upper():
            raise BridgeError("米核同步器压缩包校验失败；官方文件可能已更新，请先更新桥接器")
        with zipfile.ZipFile(archive_path) as archive:
            matches = [entry for entry in archive.infolist() if Path(entry.filename).name == MIHE_SYNC_EXE_NAME]
            if len(matches) != 1:
                raise BridgeError("米核官方压缩包中没有找到唯一的便携版同步器")
            entry = matches[0]
            if entry.is_dir() or entry.file_size < 1024 * 1024:
                raise BridgeError("米核同步器文件结构异常")
            with archive.open(entry) as source, executable_temp.open("wb") as destination:
                while block := source.read(1024 * 1024):
                    destination.write(block)
        if _sha256(executable_temp) != executable_sha256.upper():
            raise BridgeError("米核同步器程序校验失败；拒绝启动未知程序")
        executable_temp.replace(target)
        metadata = {
            "source": download_url,
            "archive_sha256": archive_sha256.upper(),
            "executable_sha256": executable_sha256.upper(),
        }
        (root / "source.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    except BridgeError:
        raise
    except Exception as exc:
        raise BridgeError(f"米核同步器下载或解压失败：{exc}") from exc
    finally:
        archive_path.unlink(missing_ok=True)
        executable_temp.unlink(missing_ok=True)
    _progress(progress, "米核同步器下载并校验完成")
    return target


def launch_mihe_sync(
    *,
    progress: ProgressCallback | None = None,
    base_dir: Path | str | None = None,
) -> Path:
    executable = ensure_mihe_sync(progress=progress, base_dir=base_dir)
    subprocess.Popen([str(executable)], cwd=str(executable.parent))
    return executable


def _resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return (base / relative_path).resolve()


def launch_mihe_sync_automated(
    draft_id: str,
    *,
    progress: ProgressCallback | None = None,
    base_dir: Path | str | None = None,
    timeout_seconds: int = 35,
) -> dict[str, Any]:
    if os.name != "nt":
        raise BridgeError("米核桌面自动化只支持 Windows")
    normalized = validate_mihe_server_draft_id(draft_id)
    executable = ensure_mihe_sync(progress=progress, base_dir=base_dir)
    script = _resource_path("scripts/run_mihe_sync_automation.ps1")
    if not script.is_file():
        raise BridgeError(f"缺少米核桌面自动化脚本：{script}")
    _progress(progress, "正在启动米核同步器并尝试自动填写 draft_id……")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-DraftId",
        normalized,
        "-MiheExe",
        str(executable),
        "-TimeoutSeconds",
        str(max(5, int(timeout_seconds))),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(executable.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(15, int(timeout_seconds) + 20),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("米核同步器已启动，但桌面自动化等待超时；请手动粘贴剪贴板中的 draft_id") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "未知错误").strip()
        raise BridgeError(f"米核桌面自动化启动失败：{detail}")
    output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(output_lines[-1]) if output_lines else {}
    except json.JSONDecodeError:
        result = {"status": "started", "detail": completed.stdout.strip()}
    result["executable"] = str(executable)
    result["draft_id"] = normalized
    return result


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
