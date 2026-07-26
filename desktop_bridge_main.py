#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import os
import traceback
from pathlib import Path

from desktop_bridge.app import main
from desktop_bridge.helper_metadata import HELPER_PRODUCT_NAME
from desktop_bridge.paths import app_data_dir


def _report_startup_error(exc: Exception) -> None:
    try:
        log_path = app_data_dir() / "logs" / "startup-error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        log_path = Path(os.getenv("TEMP") or ".") / "AIVideoCreator-startup-error.log"
    try:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{exc}\n\n启动日志：\n{log_path}",
                f"{HELPER_PRODUCT_NAME}启动失败",
                0x10,
            )
        except Exception:
            pass


def run() -> int:
    try:
        return main()
    except Exception as exc:
        _report_startup_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
