#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对整个工作流模板 JSON 进行媒体 URL 清洗。"""

import re

from config import PREVIEW_VIDEO_URLS
from utils.media import (
    needs_url_replacement,
    is_signed_url_expired,
    infer_media_ext,
    sanitize_url_segments,
    replace_urls_in_text,
    dedupe_url_segments,
)


def sanitize_template_media_urls(template, biz_type, match_key=""):
    fallback_url = PREVIEW_VIDEO_URLS.get(biz_type, "").strip()
    fallback_available = bool(fallback_url) and fallback_url.startswith(("http://", "https://")) and not is_signed_url_expired(fallback_url)
    effective_fallback = fallback_url if fallback_available else ""
    backup_candidates = []

    def collect_candidates(obj):
        if isinstance(obj, dict):
            for value in obj.values():
                collect_candidates(value)
        elif isinstance(obj, list):
            for item in obj:
                collect_candidates(item)
        elif isinstance(obj, str):
            for url in re.findall(r'https?://[^\s,"\']+', obj):
                if infer_media_ext(url) and not needs_url_replacement(url):
                    backup_candidates.append(url)

    collect_candidates(template)
    # 去重并保持顺序，避免后续替换总是命中同一条
    backup_candidates_deduped = list(dict.fromkeys(backup_candidates))
    candidates_by_ext = {}
    for candidate in backup_candidates_deduped:
        ext = infer_media_ext(candidate) or "_any"
        candidates_by_ext.setdefault(ext, []).append(candidate)
    rotate_index = {}
    seed_base = abs(hash(f"{biz_type}:{match_key}")) if match_key else 0

    def pick_backup_url(expired_url):
        target_ext = infer_media_ext(expired_url)
        pool = candidates_by_ext.get(target_ext) if target_ext else None
        if not pool:
            pool = backup_candidates_deduped
        if not pool:
            return ""
        key = target_ext or "_any"
        if key not in rotate_index:
            rotate_index[key] = seed_base % len(pool)
        idx = rotate_index[key] % len(pool)
        rotate_index[key] = idx + 1
        return pool[idx]

    _SKIP_KEYS = {"_temp", "nodeMeta", "externalData", "code"}

    def walk(obj, _parent_key=None):
        if _parent_key in _SKIP_KEYS:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in _SKIP_KEYS:
                    continue
                if isinstance(value, str):
                    updated = sanitize_url_segments(value, effective_fallback, pick_backup_url)
                    updated = replace_urls_in_text(updated, effective_fallback, pick_backup_url)
                    updated = dedupe_url_segments(updated)
                    if updated.startswith(("http://", "https://")) and needs_url_replacement(updated):
                        replacement = fallback_url if fallback_available else pick_backup_url(updated)
                        obj[key] = replacement or updated
                    else:
                        obj[key] = updated
                else:
                    walk(value, _parent_key=key)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, _parent_key=_parent_key)

    walk(template)
    return template
