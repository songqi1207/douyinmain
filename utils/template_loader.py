#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""加载 Coze 工作流 JSON 模板文件。"""

import json
import os
from pathlib import Path

from config import VIDEO_PREVIEW_PATTERNS, PREVIEW_VIDEO_URLS

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))


def load_template(template_name):
    """
    加载工作流模板文件
    """
    template_path = os.path.join(_BASE_DIR, template_name)
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"模板文件不存在: {template_path}")
    with open(template_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_first_available_template(candidates):
    for candidate in candidates:
        candidate_path = os.path.join(_BASE_DIR, candidate)
        if os.path.exists(candidate_path):
            with open(candidate_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    raise FileNotFoundError(f"模板文件不存在，候选路径: {candidates}")


def find_preview_video(biz_type):
    patterns = VIDEO_PREVIEW_PATTERNS.get(biz_type, [])
    cwd = Path(os.getcwd())
    candidates = []
    for pattern in patterns:
        candidates.extend(cwd.glob(pattern))
    files = [path for path in candidates if path.is_file()]
    if not files:
        return None
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0]


def get_preview_video_url(biz_type):
    cdn_url = PREVIEW_VIDEO_URLS.get(biz_type, "")
    if cdn_url:
        return cdn_url
    return f"/api/preview_video/{biz_type}"
