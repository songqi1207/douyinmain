"""Stable per-user paths with migration from older helper builds."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .helper_metadata import HELPER_DATA_DIRNAME, LEGACY_DATA_DIRNAME


def app_data_dir() -> Path:
    base = Path(os.getenv("APPDATA") or Path.home())
    current = (base / HELPER_DATA_DIRNAME).resolve()
    legacy = (base / LEGACY_DATA_DIRNAME).resolve()
    current.mkdir(parents=True, exist_ok=True)

    for relative in ("settings.json", "data/draft_key_imports.json"):
        source = legacy / relative
        destination = current / relative
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return current
