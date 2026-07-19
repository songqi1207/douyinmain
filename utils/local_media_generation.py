#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local fallbacks for speech synthesis and placeholder image generation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import textwrap
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from PIL import Image, ImageDraw, ImageFont

from utils.audio_probe import probe_audio_duration


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GENERATED_ROOT = _PROJECT_ROOT / "temp" / "generated"


def list_system_voices() -> list[dict]:
    """Discover the voices the Windows System.Speech engine can really use."""
    script = "\n".join(
        [
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
            "Add-Type -AssemblyName System.Speech",
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            "$voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {",
            "  [PSCustomObject]@{",
            "    id = $_.VoiceInfo.Name",
            "    name = $_.VoiceInfo.Description",
            "    culture = $_.VoiceInfo.Culture.Name",
            "    gender = [string]$_.VoiceInfo.Gender",
            "    age = [string]$_.VoiceInfo.Age",
            "  }",
            "})",
            "$synth.Dispose()",
            "$voices | ConvertTo-Json -Compress",
        ]
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    voices = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            continue
        raw_gender = str(row.get("gender") or "Neutral").lower()
        gender = raw_gender if raw_gender in {"female", "male"} else "neutral"
        culture = str(row.get("culture") or "").strip()
        voices.append(
            {
                "id": str(row["id"]).strip(),
                "name": str(row.get("name") or row["id"]).strip(),
                "gender": gender,
                "gender_label": {"female": "女声", "male": "男声", "neutral": "中性"}[gender],
                "language": culture or "未知",
                "description": f"本机已安装的 System.Speech 音色（{culture or '未标注语言'}）",
                "model": "Windows System.Speech",
                "provider": "local-system",
                "available": True,
            }
        )
    return voices


def _ensure_dir(kind: str) -> Path:
    target = _GENERATED_ROOT / kind
    target.mkdir(parents=True, exist_ok=True)
    return target


def generated_file_path(kind: str, filename: str) -> Path:
    return _ensure_dir(kind) / filename


def generated_public_url(base_url: str, kind: str, filename: str) -> str:
    return f"{base_url.rstrip('/')}/api/generated/{kind}/{quote(filename, safe='')}"


def generated_local_path_from_url(url: str) -> Path | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[0] != "api" or parts[1] != "generated":
        return None
    kind = parts[2]
    filename = unquote(parts[3])
    path = generated_file_path(kind, filename)
    return path if path.exists() else None


def _pick_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _ratio_to_size(ratio: str) -> tuple[int, int]:
    raw = str(ratio or "").strip()
    if raw == "9:16":
        return 1080, 1920
    if raw == "1:1":
        return 1080, 1080
    return 1280, 720


def _render_placeholder_audio(path: Path, text: str, speed_ratio: float) -> None:
    duration = max(1.2, min(20.0, len(str(text or "").strip()) * 0.18 / max(0.3, speed_ratio)))
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=660:duration={duration}",
        "-af",
        "volume=0.15",
        str(path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0 or not path.exists() or path.stat().st_size <= 128:
        detail = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise RuntimeError(detail or "placeholder audio generation failed")


def synthesize_speech(
    text: str,
    base_url: str,
    *,
    voice_id: str = "",
    speed_ratio: float | int | str | None = None,
    emotion: str = "",
    emotion_scale: int | float | str | None = None,
) -> dict:
    del emotion
    del emotion_scale

    content = str(text or "").strip()
    if not content:
        raise ValueError("missing text")

    task_id = str(uuid.uuid4()).upper()
    audio_dir = _ensure_dir("audio")
    text_path = audio_dir / f"{task_id}.txt"
    wav_path = audio_dir / f"{task_id}.wav"
    text_path.write_text(content, encoding="utf-8")

    voice_name = str(voice_id or "").strip()
    if voice_name.isdigit():
        voice_name = ""
    try:
        speed = float(speed_ratio if speed_ratio not in (None, "") else 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    rate = max(-10, min(10, int(round((speed - 1.0) * 20))))
    escaped_text_path = str(text_path).replace("'", "''")
    escaped_wav_path = str(wav_path).replace("'", "''")
    escaped_voice_name = voice_name.replace("'", "''")

    ps_script = "\n".join(
        [
            "Add-Type -AssemblyName System.Speech",
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            f"$synth.Rate = {rate}",
            f"$text = Get-Content -LiteralPath '{escaped_text_path}' -Raw -Encoding UTF8",
            f"$wav = '{escaped_wav_path}'",
            f"if ('{escaped_voice_name}'.Trim()) {{ $synth.SelectVoice('{escaped_voice_name}') }}",
            "$synth.SetOutputToWaveFile($wav)",
            "$synth.Speak($text)",
            "$synth.Dispose()",
        ]
    )
    synth = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if synth.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size <= 128:
        wav_path.unlink(missing_ok=True)
        detail = ((synth.stderr or "") + "\n" + (synth.stdout or "")).strip()
        raise RuntimeError(detail or "本机语音合成失败")

    try:
        text_path.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        duration = probe_audio_duration(str(wav_path))
    except Exception as exc:
        wav_path.unlink(missing_ok=True)
        raise RuntimeError(f"生成的音频无法读取：{exc}") from exc
    return {
        "code": 0,
        "data": {
            "duration": duration,
            "link": generated_public_url(base_url, "audio", wav_path.name),
        },
        "log_id": task_id,
        "msg": "ok",
    }


def generate_placeholder_image(
    prompt: str,
    base_url: str,
    *,
    ratio: str = "16:9",
    model: str = "",
    key: str = "",
) -> dict:
    del key

    content = str(prompt or "").strip()
    if not content:
        raise ValueError("missing prompt")

    task_id = str(uuid.uuid4()).upper()
    image_dir = _ensure_dir("image")
    image_path = image_dir / f"{task_id}.png"

    width, height = _ratio_to_size(ratio)
    digest = hashlib.sha256(f"{content}|{ratio}|{model}".encode("utf-8")).digest()
    c1 = tuple(40 + digest[i] % 120 for i in range(3))
    c2 = tuple(90 + digest[i] % 120 for i in range(3, 6))

    image = Image.new("RGB", (width, height), c1)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        mix = y / max(1, height - 1)
        color = tuple(int(c1[idx] * (1 - mix) + c2[idx] * mix) for idx in range(3))
        draw.line((0, y, width, y), fill=color)

    pad = int(min(width, height) * 0.07)
    font_title = _pick_font(max(28, width // 26))
    font_body = _pick_font(max(20, width // 38))
    overlay = (255, 255, 255)
    secondary = (230, 230, 230)

    draw.rectangle((pad, pad, width - pad, height - pad), outline=overlay, width=max(3, width // 320))
    draw.text((pad * 1.2, pad * 1.1), "LOCAL PLACEHOLDER", fill=overlay, font=font_title)
    if model:
        draw.text((pad * 1.2, pad * 1.9), f"model: {model}", fill=secondary, font=font_body)

    snippet = content[:180]
    wrapped = textwrap.wrap(snippet, width=18 if width < height else 24)[:8]
    body_text = "\n".join(wrapped)
    draw.multiline_text(
        (pad * 1.2, height * 0.28),
        body_text,
        fill=overlay,
        font=font_body,
        spacing=max(10, font_body.size // 2),
    )

    image.save(image_path, format="PNG")
    return {
        "message": "ok (local placeholder image, not Mihe/Jimeng real generation)",
        "task_id": task_id,
        "url": generated_public_url(base_url, "image", image_path.name),
    }
