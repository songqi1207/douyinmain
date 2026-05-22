#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻书动画生成器。

用 Pillow 生成翻书效果的 GIF 动图：
- 多张图片依次以 3D 透视翻页效果切换
- 输出为 GIF 动图，可作为片头素材
"""

import io
import math
import requests
from PIL import Image, ImageDraw

from config import HEADERS


def download_image(url, size=(540, 720)):
    """下载图片并缩放到指定尺寸。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        img = img.resize(size, Image.LANCZOS)
        return img
    except Exception as e:
        # 返回纯色占位图
        img = Image.new("RGBA", size, (60, 60, 80, 255))
        draw = ImageDraw.Draw(img)
        draw.text((size[0]//4, size[1]//2), "Loading...", fill=(200, 200, 200))
        return img


def perspective_transform(img, progress):
    """
    模拟翻页的透视变换。
    progress: 0.0（正面）到 1.0（完全翻走）
    返回变换后的图片（带透明背景）。
    """
    w, h = img.size
    
    # 翻页角度：0° 到 90°
    angle = progress * math.pi / 2
    
    # 计算透视变换后的宽度（cos缩小）
    new_w = max(1, int(w * math.cos(angle)))
    
    if new_w < 2:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    
    # 缩放图片宽度模拟透视
    squeezed = img.resize((new_w, h), Image.LANCZOS)
    
    # 放到原始尺寸的画布上（右对齐，模拟从右边翻走）
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(squeezed, (w - new_w, 0))
    
    # 添加阴影效果（翻页时边缘变暗）
    if progress > 0.1:
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, int(progress * 80)))
        canvas = Image.alpha_composite(canvas, shadow)
    
    return canvas


def generate_flip_book_gif(image_urls, output_path, 
                           page_size=(540, 720),
                           canvas_size=(1080, 1920),
                           flip_frames=12,
                           hold_frames=8,
                           frame_duration=80):
    """
    生成翻书效果 GIF。
    
    Args:
        image_urls: 图片 URL 列表
        output_path: 输出 GIF 路径
        page_size: 每页图片尺寸
        canvas_size: 画布尺寸（竖屏 1080x1920）
        flip_frames: 翻页动画帧数
        hold_frames: 每页停留帧数
        frame_duration: 每帧时长（毫秒）
    
    Returns:
        输出文件路径
    """
    # 下载所有图片
    pages = []
    for url in image_urls:
        img = download_image(url, page_size)
        pages.append(img)
    
    if not pages:
        return None
    
    # 计算图片在画布上的位置（居中）
    cx = (canvas_size[0] - page_size[0]) // 2
    cy = (canvas_size[1] - page_size[1]) // 2
    
    frames = []
    bg_color = (15, 15, 25)  # 深色背景
    
    for page_idx in range(len(pages)):
        current_page = pages[page_idx]
        next_page = pages[page_idx + 1] if page_idx + 1 < len(pages) else None
        
        # 停留帧：当前页静止显示
        for _ in range(hold_frames):
            frame = Image.new("RGB", canvas_size, bg_color)
            frame.paste(current_page, (cx, cy), current_page)
            frames.append(frame)
        
        # 翻页帧：当前页翻走，露出下一页
        if next_page:
            for fi in range(flip_frames):
                progress = (fi + 1) / flip_frames
                frame = Image.new("RGB", canvas_size, bg_color)
                
                # 底层：下一页（静止）
                frame.paste(next_page, (cx, cy), next_page)
                
                # 顶层：当前页（翻走中）
                flipped = perspective_transform(current_page, progress)
                frame.paste(flipped, (cx, cy), flipped)
                
                frames.append(frame)
    
    # 最后一页多停留一会
    if pages:
        last_page = pages[-1]
        for _ in range(hold_frames * 2):
            frame = Image.new("RGB", canvas_size, bg_color)
            frame.paste(last_page, (cx, cy), last_page)
            frames.append(frame)
    
    if not frames:
        return None
    
    # 保存为 GIF
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=frame_duration,
        loop=0,
    )
    
    return output_path


def generate_flip_book_for_god(god_name, image_urls, output_dir="covers"):
    """
    为指定神明生成翻书片头 GIF。
    
    Returns:
        本地文件路径
    """
    import os
    import re
    
    safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '', god_name)[:20]
    output_path = os.path.join(output_dir, f"flip_intro_{safe_name}.gif")
    
    result = generate_flip_book_gif(
        image_urls=image_urls,
        output_path=output_path,
        page_size=(540, 720),
        canvas_size=(1080, 1920),
        flip_frames=10,
        hold_frames=6,
        frame_duration=100,
    )
    
    return result
