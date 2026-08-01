"""Compress completed device exports and publish them to object storage."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import requests


class VideoDeliveryError(RuntimeError):
    """Raised when the optional compressed R2 delivery path fails."""


_DELIVERY_LOCK = threading.Lock()


def r2_export_configured() -> bool:
    enabled = (os.getenv("R2_EXPORT_ENABLED") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return enabled and all(
        (os.getenv(name) or "").strip()
        for name in (
            "R2_EXPORT_UPLOAD_URL",
            "R2_EXPORT_PUBLIC_BASE_URL",
            "R2_EXPORT_UPLOAD_TOKEN",
        )
    )


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name) or default))
    except ValueError:
        return default


def _crf() -> int:
    try:
        return min(30, max(16, int(os.getenv("R2_EXPORT_VIDEO_CRF") or 20)))
    except ValueError:
        return 20


def _preview_crf() -> int:
    try:
        return min(30, max(18, int(os.getenv("R2_EXPORT_PREVIEW_CRF") or 23)))
    except ValueError:
        return 23


def compress_video_for_web(source: Path, destination: Path) -> Path:
    """Create a low-bandwidth H.264 preview for smooth browser playback."""

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise VideoDeliveryError("导出原片不存在，无法压缩")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.stem}.{uuid4().hex}.encoding.mp4"
    )
    preset = (os.getenv("R2_EXPORT_VIDEO_PRESET") or "medium").strip() or "medium"
    audio_bitrate = (os.getenv("R2_EXPORT_PREVIEW_AUDIO_BITRATE") or "96k").strip() or "96k"
    video_bitrate = (os.getenv("R2_EXPORT_PREVIEW_MAXRATE") or "1200k").strip() or "1200k"
    video_buffer = (os.getenv("R2_EXPORT_PREVIEW_BUFSIZE") or "2400k").strip() or "2400k"
    command = [
        os.getenv("FFMPEG_BINARY") or "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-sn",
        "-dn",
        "-c:v",
        "libx264",
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
        "-preset",
        preset,
        "-crf",
        str(_preview_crf()),
        "-maxrate",
        video_bitrate,
        "-bufsize",
        video_buffer,
        "-g",
        "60",
        "-keyint_min",
        "60",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_positive_int("R2_EXPORT_COMPRESSION_TIMEOUT_SECONDS", 3600),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        temporary.unlink(missing_ok=True)
        raise VideoDeliveryError(f"视频压缩程序无法完成：{exc}") from exc
    if completed.returncode != 0 or not temporary.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        temporary.unlink(missing_ok=True)
        raise VideoDeliveryError(
            f"视频压缩失败（FFmpeg 退出码 {completed.returncode}）"
            + (f"：{detail}" if detail else "")
        )
    if temporary.stat().st_size < 12:
        temporary.unlink(missing_ok=True)
        raise VideoDeliveryError("视频压缩结果为空")
    with temporary.open("rb") as stream:
        if b"ftyp" not in stream.read(64):
            temporary.unlink(missing_ok=True)
            raise VideoDeliveryError("视频压缩结果不是有效的 MP4")

    os.replace(temporary, destination)
    return destination


def remux_video_for_web(source: Path, destination: Path) -> Path:
    """Losslessly strip unsupported metadata and move MP4 indexes to the front."""

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise VideoDeliveryError("导出原片不存在，无法优化")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.stem}.{uuid4().hex}.remuxing.mp4"
    )
    command = [
        os.getenv("FFMPEG_BINARY") or "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-ignore_unknown",
        "-err_detect",
        "ignore_err",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-sn",
        "-dn",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_positive_int("R2_EXPORT_REMUX_TIMEOUT_SECONDS", 600),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        temporary.unlink(missing_ok=True)
        raise VideoDeliveryError(f"视频快速优化无法完成：{exc}") from exc
    if completed.returncode != 0 or not temporary.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        temporary.unlink(missing_ok=True)
        raise VideoDeliveryError(
            f"视频快速优化失败（FFmpeg 退出码 {completed.returncode}）"
            + (f"：{detail}" if detail else "")
        )
    if temporary.stat().st_size < 12:
        temporary.unlink(missing_ok=True)
        raise VideoDeliveryError("视频快速优化结果为空")
    with temporary.open("rb") as stream:
        if b"ftyp" not in stream.read(64):
            temporary.unlink(missing_ok=True)
            raise VideoDeliveryError("视频快速优化结果不是有效 MP4")
    os.replace(temporary, destination)
    return destination


def upload_video_to_r2(source: Path, object_name: str) -> str:
    source = Path(source).resolve()
    safe_name = Path(object_name).name
    if not source.is_file() or not safe_name.lower().endswith(".mp4"):
        raise VideoDeliveryError("R2 上传文件无效")
    upload_base = (os.getenv("R2_EXPORT_UPLOAD_URL") or "").strip().rstrip("/")
    public_base = (os.getenv("R2_EXPORT_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    token = (os.getenv("R2_EXPORT_UPLOAD_TOKEN") or "").strip()
    if not upload_base or not public_base or not token:
        raise VideoDeliveryError("R2 视频上传尚未配置")
    target_url = f"{upload_base}/{quote(safe_name)}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "video/mp4",
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=31536000, immutable",
    }
    try:
        with source.open("rb") as body:
            response = requests.put(
                target_url,
                headers=headers,
                data=body,
                timeout=(
                    _positive_int("R2_EXPORT_CONNECT_TIMEOUT_SECONDS", 20),
                    _positive_int("R2_EXPORT_UPLOAD_TIMEOUT_SECONDS", 900),
                ),
            )
    except requests.RequestException as exc:
        raise VideoDeliveryError(f"R2 视频上传失败：{exc}") from exc
    if response.status_code not in {200, 201, 204}:
        detail = (response.text or "").strip()[:300]
        raise VideoDeliveryError(
            f"R2 视频上传失败（HTTP {response.status_code}）" + (f"：{detail}" if detail else "")
        )
    return f"{public_base}/{quote(safe_name)}"


def publish_device_video(job_id: str, source: Path) -> tuple[str, str, int, int, str]:
    """Upload a full-quality download plus a low-bandwidth browser preview."""

    source = Path(source).resolve()
    delivery_id = uuid4().hex[:12]
    preview_output = source.with_name(f".{job_id}-device-preview.{delivery_id}.mp4")
    download_output = source.with_name(f".{job_id}-device-original.{delivery_id}.mp4")
    original_size = source.stat().st_size
    preview_source = source
    download_source = source
    delivery_mode = "preview"
    with _DELIVERY_LOCK:
        try:
            try:
                download_source = remux_video_for_web(source, download_output)
            except VideoDeliveryError:
                download_source = source
            download_url = upload_video_to_r2(
                download_source,
                f"{job_id}-device-original-{delivery_id}.mp4",
            )
            try:
                preview_source = compress_video_for_web(source, preview_output)
                preview_url = upload_video_to_r2(
                    preview_source,
                    f"{job_id}-device-preview-{delivery_id}.mp4",
                )
            except VideoDeliveryError:
                delivery_mode = "original_fallback"
                preview_source = download_source
                preview_url = download_url
            return preview_url, download_url, original_size, preview_source.stat().st_size, delivery_mode
        finally:
            preview_output.unlink(missing_ok=True)
            download_output.unlink(missing_ok=True)
