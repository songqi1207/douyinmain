#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻书帧生成器。

生成翻页过程的中间帧图片，上传到 CDN。
- 背景使用 background.png
- 图片保持原始比例，居中放置
- 画布尺寸匹配工作流（1920×1080）
- 输出高质量 JPEG
"""

import io
import math
import os
import time
import requests
from PIL import Image, ImageDraw

from config import HEADERS, CDN_TOKEN, PROJECT_ROOT
from utils.cover import upload_cover_to_cdn

# 背景图路径
BG_PATH = os.path.join(PROJECT_ROOT, "background.png")
# 画布尺寸（匹配工作流 1920x1080 横屏）
CANVAS_W = 1920
CANVAS_H = 1080


def _load_background():
    """加载背景图，缩放到画布尺寸。"""
    if os.path.exists(BG_PATH):
        bg = Image.open(BG_PATH).convert("RGB")
        bg = bg.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
        return bg
    return Image.new("RGB", (CANVAS_W, CANVAS_H), (20, 20, 30))


def _download_image(url):
    """下载图片，保持原始比例，不强制缩放。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        return img
    except Exception:
        return Image.new("RGBA", (400, 600), (60, 60, 80, 255))


def _fit_image_to_canvas(img, max_w=800, max_h=900):
    """保持比例缩放图片，使其适合画布中央区域。"""
    w, h = img.size
    ratio = min(max_w / w, max_h / h)
    if ratio < 1:
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    return img


def _make_flip_frame(bg, current_img, next_img, progress):
    """
    生成一帧翻页画面。
    progress: 0.0（正面）到 1.0（完全翻走）
    """
    frame = bg.copy()
    
    # 居中位置
    def paste_centered(frame, img):
        w, h = img.size
        x = (CANVAS_W - w) // 2
        y = (CANVAS_H - h) // 2
        frame.paste(img, (x, y), img if img.mode == "RGBA" else None)
    
    # 底层：下一页
    if next_img:
        paste_centered(frame, next_img)
    
    # 顶层：当前页翻走（透视缩小）
    if progress < 0.95:
        angle = progress * math.pi / 2
        orig_w, orig_h = current_img.size
        new_w = max(2, int(orig_w * math.cos(angle)))
        
        squeezed = current_img.resize((new_w, orig_h), Image.LANCZOS)
        # 创建透明画布，图片右对齐（从右边翻走）
        page_canvas = Image.new("RGBA", (orig_w, orig_h), (0, 0, 0, 0))
        page_canvas.paste(squeezed, (orig_w - new_w, 0))
        
        paste_centered(frame, page_canvas)
    
    return frame


def generate_flip_frames(image_urls, output_dir=None):
    """
    生成翻书帧序列并上传到 CDN。
    
    每张图：1帧静止 + 2帧翻页中间态
    最后一张：只有静止帧
    
    Returns:
        list of CDN URLs（按播放顺序）
    """
    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "covers", "flip_frames")
    os.makedirs(output_dir, exist_ok=True)
    
    bg = _load_background()
    
    # 下载并适配图片
    pages = []
    for url in image_urls:
        img = _download_image(url)
        img = _fit_image_to_canvas(img)
        pages.append(img)
    
    # 生成帧序列
    all_frames = []  # (frame_image, description)
    
    for pi in range(len(pages)):
        current = pages[pi]
        next_page = pages[pi + 1] if pi + 1 < len(pages) else None
        
        # 静止帧
        frame = bg.copy()
        w, h = current.size
        x = (CANVAS_W - w) // 2
        y = (CANVAS_H - h) // 2
        frame.paste(current, (x, y), current if current.mode == "RGBA" else None)
        all_frames.append((frame, f"page{pi}_hold"))
        
        # 翻页中间帧（只有非最后一页才需要）
        if next_page:
            for progress in [0.35, 0.7]:
                flip_frame = _make_flip_frame(bg, current, next_page, progress)
                all_frames.append((flip_frame, f"page{pi}_flip{int(progress*100)}"))
    
    # 保存并上传
    frame_urls = []
    upload_count = 0
    
    for idx, (frame_img, desc) in enumerate(all_frames):
        frame_path = os.path.join(output_dir, f"frame_{idx:03d}_{desc}.jpg")
        frame_img.save(frame_path, "JPEG", quality=95)
        
        if CDN_TOKEN and upload_count < 16:  # 限速保护
            url = upload_cover_to_cdn(frame_path, token=CDN_TOKEN)
            if url:
                frame_urls.append(url)
                upload_count += 1
                continue
        
        # 回退：用本地路径
        frame_urls.append(frame_path)
    
    return frame_urls
