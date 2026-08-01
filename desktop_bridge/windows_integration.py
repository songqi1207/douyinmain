"""Per-user Windows installation, auto-start and browser protocol helpers."""

from __future__ import annotations

import base64
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

from desktop_bridge.helper_metadata import HELPER_BINARY_NAME, HELPER_PRODUCT_NAME
from desktop_bridge.paths import app_data_dir


PROTOCOL_SCHEME = "douyin-draft"
MUTEX_NAME = "Local\\AIVideoCreator.UserAgent"
_mutex_handle = None


def install_dir() -> Path:
    root = Path(os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or Path.home())
    target = root / "AIVideoCreator"
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def _installed_target(source: Path) -> Path:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    return install_dir() / f"{Path(HELPER_BINARY_NAME).stem}-{digest}.exe"


def _register_windows_integration(executable: Path) -> None:
    if os.name != "nt":
        return
    import winreg

    command = f'"{executable}"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROTOCOL_SCHEME}") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{HELPER_PRODUCT_NAME}")
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
        try:
            winreg.DeleteValue(key, "DouyinDraftBridge")
        except FileNotFoundError:
            pass
        winreg.SetValueEx(
            key,
            "AIVideoCreator",
            0,
            winreg.REG_SZ,
            f"{command} --background",
        )


def _stop_other_installed_helpers(current_target: Path) -> None:
    """Stop an older hashed helper before launching the newly installed build."""
    if os.name != "nt":
        return
    escaped_dir = str(install_dir()).replace("'", "''")
    escaped_target = str(current_target.resolve()).replace("'", "''")
    script = (
        f"$helperDir = [IO.Path]::GetFullPath('{escaped_dir}'); "
        f"$current = [IO.Path]::GetFullPath('{escaped_target}'); "
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.ProcessId -ne $PID -and $_.ExecutablePath -and "
        "[IO.Path]::GetDirectoryName($_.ExecutablePath) -eq $helperDir -and "
        "[IO.Path]::GetFileName($_.ExecutablePath) -like 'AIVideoCreator-*.exe' -and "
        "[IO.Path]::GetFullPath($_.ExecutablePath) -ne $current "
        "} | ForEach-Object { "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue "
        "}"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            check=False,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(0.8)
    except (OSError, subprocess.SubprocessError):
        pass


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
        _stop_other_installed_helpers(target)
        relaunch_arguments = list(arguments) or ["--background"]
        subprocess.Popen(
            [str(target), *relaunch_arguments],
            cwd=str(target.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    _register_windows_integration(source)
    return False


def wait_for_replaced_process(process_id: int, timeout_ms: int = 20_000) -> None:
    """Wait until the old helper releases its single-instance mutex.

    The downloaded updater used to relaunch the installed build immediately.
    On slower Windows machines that build could observe the old mutex, exit,
    and then leave no helper running once the old process closed.
    """
    if os.name != "nt" or process_id <= 0 or process_id == os.getpid():
        return
    kernel32 = ctypes.windll.kernel32
    synchronize = 0x00100000
    handle = kernel32.OpenProcess(synchronize, False, int(process_id))
    if not handle:
        return
    try:
        kernel32.WaitForSingleObject(handle, max(0, int(timeout_ms)))
    finally:
        kernel32.CloseHandle(handle)


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
