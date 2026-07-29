"""Self-update launcher for the packaged Windows helper."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

from desktop_bridge.helper_metadata import HELPER_BINARY_NAME
from desktop_bridge.paths import app_data_dir


def _site_base_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if url.endswith("/business"):
        url = url[:-9]
    if not url.startswith(("http://", "https://")):
        raise ValueError("网站地址必须以 http:// 或 https:// 开头")
    return url


def download_and_launch_update(site_url: str) -> Path:
    """Download the latest helper and run it so it can install over this build."""
    base_url = _site_base_url(site_url)
    download_url = urljoin(base_url + "/", "api/v1/downloads/draft-bridge")
    update_dir = app_data_dir() / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    temporary = update_dir / f"{Path(HELPER_BINARY_NAME).stem}-update-{int(time.time())}.exe"
    partial = temporary.with_suffix(".download")

    with requests.get(download_url, stream=True, timeout=(20, 180)) as response:
        response.raise_for_status()
        digest = hashlib.sha256()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
        expected = str(response.headers.get("X-Content-SHA256") or "").strip().lower()
        actual = digest.hexdigest()
        if expected and expected != actual:
            raise RuntimeError("助手更新包校验失败")

    os.replace(partial, temporary)
    subprocess.Popen(
        [str(temporary), "--background"],
        cwd=str(temporary.parent),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return temporary
