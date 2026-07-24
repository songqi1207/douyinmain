"""Per-user Windows installation, auto-start and browser protocol helpers."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROTOCOL_SCHEME = "douyin-draft"
MUTEX_NAME = "Local\\DouyinDraftBridge.UserAgent"
_mutex_handle = None


def app_data_dir() -> Path:
    root = Path(os.getenv("APPDATA") or Path.home()) / "DouyinDraftBridge"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def install_dir() -> Path:
    root = Path(os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or Path.home())
    target = root / "DouyinDraftBridge"
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def _installed_target(source: Path) -> Path:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    return install_dir() / f"DouyinDraftBridge-{digest}.exe"


def _register_windows_integration(executable: Path) -> None:
    if os.name != "nt":
        return
    import winreg

    command = f'"{executable}"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL_SCHEME}") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:抖音工作流剪映导出助手")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        rf"Software\Classes\{PROTOCOL_SCHEME}\DefaultIcon",
    ) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"{executable},0")
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        rf"Software\Classes\{PROTOCOL_SCHEME}\shell\open\command",
    ) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'{command} --protocol "%1"')
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
    ) as key:
        winreg.SetValueEx(
            key,
            "DouyinDraftBridge",
            0,
            winreg.REG_SZ,
            f"{command} --background",
        )


def install_for_current_user(arguments: list[str]) -> bool:
    """Install a frozen build per-user and relaunch it. Returns True to exit."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    source = Path(sys.executable).resolve()
    target = _installed_target(source)
    if source != target:
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            temporary = target.with_suffix(f".{os.getpid()}.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        _register_windows_integration(target)
        subprocess.Popen(
            [str(target), *arguments],
            cwd=str(target.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    _register_windows_integration(source)
    return False


def acquire_single_instance() -> bool:
    """Return False when another GUI/background instance already owns the mutex."""
    global _mutex_handle
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True
    _mutex_handle = handle
    return int(kernel32.GetLastError()) != 183


def wake_signal_path() -> Path:
    return app_data_dir() / "wake.signal.json"


def notify_primary(protocol_url: str = f"{PROTOCOL_SCHEME}://open") -> None:
    path = wake_signal_path()
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"url": protocol_url, "created_at": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def consume_wake_signal() -> str | None:
    path = wake_signal_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        path.unlink()
    except (OSError, ValueError, TypeError):
        return None
    if time.time() - float(payload.get("created_at") or 0) > 120:
        return None
    return str(payload.get("url") or "")


def parse_protocol_url(value: str) -> dict:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() != PROTOCOL_SCHEME:
        return {}
    query = parse_qs(parsed.query)
    return {
        "action": (parsed.netloc or parsed.path.strip("/") or "wake").lower(),
        "site_url": str((query.get("site") or [""])[0]).strip(),
        "pairing_code": str((query.get("code") or [""])[0]).strip().upper(),
    }
