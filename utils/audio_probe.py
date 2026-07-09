#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audio duration probing utilities backed by ffprobe."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def _is_remote_target(value: str) -> bool:
    if not isinstance(value, str):
        return False
    scheme = (urlsplit(value).scheme or "").lower()
    return scheme in {"http", "https"}


def normalize_audio_target(value: str) -> str:
    target = (value or "").strip()
    if not target:
        raise ValueError("missing audio target")
    if _is_remote_target(target):
        return target

    path = Path(target).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"audio file not found: {path}")
    return str(path)


def probe_audio_duration(target: str, timeout_sec: int = 20) -> float:
    normalized = normalize_audio_target(target)
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        normalized,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "ffprobe failed"
        raise RuntimeError(detail)

    try:
        payload = json.loads(proc.stdout or "{}")
        duration = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("unable to parse ffprobe duration output") from exc

    if duration < 0:
        raise RuntimeError("invalid negative duration")
    return duration
