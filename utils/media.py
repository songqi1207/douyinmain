#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""媒体 URL 校验、去重、清洗、替换工具函数。"""

import re
import time
from urllib.parse import parse_qs, urlsplit

from config import BLOCKED_MEDIA_HOSTS, PLACEHOLDER_MEDIA_HOSTS, CIGARETTE_STYLE_HINTS


def is_signed_url_expired(url):
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    try:
        query = parse_qs(urlsplit(url).query)
        expires = (query.get("x-expires") or [""])[0]
        if not expires.isdigit():
            return False
        return int(expires) <= int(time.time())
    except Exception:
        return False


def is_blocked_media_url(url):
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    try:
        hostname = (urlsplit(url).hostname or "").lower()
        return hostname in BLOCKED_MEDIA_HOSTS
    except Exception:
        return False


def is_placeholder_media_url(url):
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return True
        # 本地封面服务是可用资源，不应被当作占位链接替换掉
        if hostname in {"localhost", "127.0.0.1"} and (parsed.path or "").startswith("/api/cover/"):
            return False
        if hostname in PLACEHOLDER_MEDIA_HOSTS:
            return True
        if hostname.endswith((".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mp3")):
            return True
        return False
    except Exception:
        return True


def needs_url_replacement(url):
    return is_signed_url_expired(url) or is_blocked_media_url(url) or is_placeholder_media_url(url)


def build_cigarette_match_key(cigarette_name):
    name = (cigarette_name or "").strip()
    if not name:
        return ""
    for keywords, style_tag in CIGARETTE_STYLE_HINTS:
        if any(keyword in name for keyword in keywords):
            return f"{name}|{style_tag}"
    return f"{name}|default"


def dedupe_url_segments(value):
    if not isinstance(value, str):
        return value
    if not re.search(r'https?://', value):
        return value

    if '，' in value:
        splitter = '，'
    elif ',' in value:
        splitter = ','
    elif '\n' in value:
        splitter = '\n'
    else:
        return value

    parts = [seg.strip() for seg in value.split(splitter)]
    if len(parts) <= 1:
        return value

    seen = set()
    deduped = []
    for part in parts:
        if not part:
            continue
        if part in seen:
            continue
        seen.add(part)
        deduped.append(part)
    return splitter.join(deduped) if deduped else value


def infer_media_ext(url):
    if not isinstance(url, str):
        return ""
    matched = re.search(r'\.(mp4|mov|m4v|png|jpg|jpeg|webp|mp3|wav|aac)\b', url, re.IGNORECASE)
    return matched.group(1).lower() if matched else ""


def sanitize_url_segments(value, fallback_url="", backup_picker=None):
    if not isinstance(value, str):
        return value
    if not re.search(r'https?://', value):
        return value

    splitter = None
    for candidate in ('，', ',', '\n'):
        parts = [seg.strip() for seg in value.split(candidate)]
        if len(parts) > 1 and all(part.startswith(("http://", "https://")) for part in parts if part):
            splitter = candidate
            break

    if not splitter:
        return value

    parts = [seg.strip() for seg in value.split(splitter)]
    cleaned = []
    seen = set()
    for part in parts:
        if not part:
            continue
        target = part
        if needs_url_replacement(part):
            if fallback_url:
                target = fallback_url
            elif callable(backup_picker):
                replacement = backup_picker(part)
                if replacement:
                    target = replacement
                else:
                    continue
            else:
                continue
        if target in seen:
            continue
        seen.add(target)
        cleaned.append(target)

    if cleaned:
        return splitter.join(cleaned)
    return fallback_url or value


def replace_urls_in_text(value, fallback_url="", backup_picker=None):
    if not isinstance(value, str) or "http" not in value:
        return value

    def _replace(match):
        url = match.group(0)
        if not needs_url_replacement(url):
            return url
        if fallback_url:
            return fallback_url
        if callable(backup_picker):
            replacement = backup_picker(url)
            if replacement:
                return replacement
        return ""

    replaced = re.sub(r'https?://[^\s,"\']+', _replace, value)
    # 清理替换后可能出现的连续分隔符
    replaced = re.sub(r'([，,\n])\1+', r'\1', replaced)
    replaced = re.sub(r'^[，,\n]+|[，,\n]+$', "", replaced)
    return replaced
