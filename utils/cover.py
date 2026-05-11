#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面图片下载、保存、删除及 URL 转换。"""

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from config import COVER_DIR, HEADERS

_log = logging.getLogger("crawlers.cover")


def remove_previous_covers_for_book(safe_name):
    """写入新封面前删除该书在 covers 下已存在的旧文件（同书名清洗前缀），避免越积越多。"""
    safe_name = (safe_name or "").strip()
    if not safe_name:
        return
    prefix = f"{safe_name}_"
    try:
        for entry in os.scandir(COVER_DIR):
            if not entry.is_file():
                continue
            name = entry.name
            if name.startswith(prefix) and name.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                try:
                    os.remove(entry.path)
                except OSError as e:
                    print(f"删除旧封面失败 {entry.path}: {e}")
    except OSError as e:
        print(f"扫描封面目录失败: {e}")


def download_and_save_cover(cover_url, book_name, session=None, extra_headers=None):
    """
    下载封面图片并保存到本地
    """
    try:
        if not session:
            session = requests.Session()
            session.headers.update(HEADERS)

        req_headers = {**session.headers, **(extra_headers or {})}
        resp = session.get(cover_url, timeout=15, stream=True, headers=req_headers)
        if resp.status_code != 200:
            return None

        image_data = resp.content
        content_type = resp.headers.get('Content-Type', '')
        ext = '.jpg'
        if 'png' in content_type:
            ext = '.png'
        elif 'webp' in content_type:
            ext = '.webp'

        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '', book_name)[:30]
        remove_previous_covers_for_book(safe_name)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{safe_name}_{timestamp}{ext}"
        filepath = os.path.join(COVER_DIR, filename)

        with open(filepath, 'wb') as f:
            f.write(image_data)

        return str(Path(filepath).resolve())

    except Exception as e:
        print(f"下载封面失败: {e}")
        return None


def workflow_public_base(override=""):
    """
    写入工作流 JSON 里封面图 URL 的站点根地址。
    优先 PUBLIC_BASE_URL（公网/ngrok，供 Coze 云端拉图）；否则用本次 HTTP 请求的 host；最后回退本机端口。
    """
    env = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    o = (override or "").strip().rstrip("/")
    if o:
        return o
    return f"http://127.0.0.1:{int(os.getenv('PORT', '5001'))}"


def cover_url_for_coze_workflow(cover_raw, public_base=""):
    """
    Coze 开始节点「pic」需要可访问的 http(s) 图片地址；本地磁盘路径会转为 {base}/api/cover/文件名。
    """
    cover = (cover_raw or "").strip()
    if not cover:
        return ""
    if cover.startswith(("http://", "https://")):
        return cover
    base = workflow_public_base(public_base)
    basename = os.path.basename(cover.replace("\\", "/"))
    if not basename:
        return ""
    return f"{base}/api/cover/{quote(basename, safe='')}"


def _ensure_jpeg_for_cdn(local_path):
    """
    确保图片是 JPEG 格式且宽度 >= 720px（Coze 封面节点要求）。
    返回处理后的文件路径（可能是新临时文件）。
    Pillow 不可用时返回原路径。
    """
    try:
        from PIL import Image
        import io
        img = Image.open(local_path).convert("RGB")
        w, h = img.size
        if w < 720:
            scale = 720 / w
            resample = getattr(Image, "LANCZOS", None) or getattr(Image, "ANTIALIAS", Image.BICUBIC)
            img = img.resize((720, int(h * scale)), resample)
        out_path = local_path + "_cdn.jpg"
        img.save(out_path, "JPEG", quality=90)
        return out_path
    except Exception:
        return local_path


def upload_cover_to_cdn(local_path, token="", storage_id=None, expire_days=None, remove_exif=None):
    """
    上传本地封面到闪电图床（boltp.com），返回公网 URL。失败返回空串。

    官方文档要点（https://www.boltp.com/api/v2/upload）：
      - multipart/form-data
      - file            binary          必填
      - storage_id      int             必填（免费=2，VIP=3）
      - is_public       boolean         默认 false → 必须传 "true"/"false" 字符串，传 1 会 422
      - is_remove_exif  boolean         可选
      - expired_at      "yyyy-MM-dd HH:mm:ss"  可选；不传则按账号默认策略
      - 429 / 422 单独处理，便于排查

    参数：
      token / storage_id / expire_days / remove_exif 为 None 时，读配置默认值。
      expire_days <= 0 表示不附带过期时间。
    """
    from config import CDN_STORAGE_ID, CDN_EXPIRE_DAYS, CDN_REMOVE_EXIF, CDN_TOKEN as _CFG_TOKEN

    # token 为空时自动 fallback 到配置文件里的 CDN_TOKEN
    if not token:
        token = _CFG_TOKEN
    if storage_id is None:
        storage_id = CDN_STORAGE_ID
    if expire_days is None:
        expire_days = CDN_EXPIRE_DAYS
    if remove_exif is None:
        remove_exif = CDN_REMOVE_EXIF

    if not local_path or not os.path.isfile(local_path):
        return ""

    upload_path = _ensure_jpeg_for_cdn(local_path)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    form_data = {
        "storage_id": str(int(storage_id)),
        # boltp 的 Laravel `boolean` 校验只认 "1"/"0"（整数 1 会被当类型错误，字符串 "true"/"false" 在该版本也会 422）
        "is_public": "1",
        "is_remove_exif": "1" if remove_exif else "0",
    }
    if expire_days and expire_days > 0:
        form_data["expired_at"] = (
            datetime.now() + timedelta(days=int(expire_days))
        ).strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(upload_path, "rb") as f:
            filename = os.path.basename(upload_path)
            resp = requests.post(
                "https://www.boltp.com/api/v2/upload",
                headers=headers,
                files={"file": (filename, f, "image/jpeg")},
                data=form_data,
                timeout=30,
            )
    except requests.RequestException as e:
        _log.warning("图床上传网络异常: %s (path=%s)", e, local_path)
        return ""
    finally:
        if upload_path != local_path:
            try:
                os.remove(upload_path)
            except OSError:
                pass

    # 尝试解析 JSON（失败时体面打印原始片段）
    try:
        data = resp.json()
    except ValueError:
        _log.warning(
            "图床上传返回非 JSON (status=%s body=%s)",
            resp.status_code, (resp.text or "")[:200],
        )
        return ""

    if resp.status_code == 429:
        _log.warning("图床上传被限流 429: %s", data.get("message") or "")
        return ""

    if resp.status_code == 401 or resp.status_code == 403:
        _log.warning("图床上传鉴权失败 %s: %s（检查 CDN_TOKEN）", resp.status_code, data.get("message"))
        return ""

    if resp.status_code == 422:
        errs = ((data.get("data") or {}).get("errors") or {})
        _log.warning("图床上传参数错误 422: %s", errs or data.get("message"))
        return ""

    if resp.status_code not in (200, 201) or (data.get("status") and data.get("status") != "success"):
        _log.warning("图床上传失败 status=%s msg=%s", resp.status_code, data.get("message"))
        return ""

    public_url = ((data.get("data") or {}).get("public_url") or "").strip()
    if not public_url:
        _log.warning("图床返回成功但 public_url 为空: %s", data)
        return ""

    _log.info("图床上传成功: %s", public_url)
    return public_url


def upload_to_boltp(local_path, token=""):
    """向后兼容别名，实际调用 upload_cover_to_cdn。"""
    return upload_cover_to_cdn(local_path, token)


def attach_cover_preview_to_book_info(book_info, request_obj=None):
    """封面字段为本地路径时，补充可在浏览器中显示的 cover_preview_url（仍通过 /api/cover 读取）。"""
    if not book_info or request_obj is None:
        return
    ci = (book_info.get("cover") or "").strip()
    if not ci or ci.startswith(("http://", "https://")):
        return
    base = os.path.basename(ci.replace("\\", "/"))
    if not base:
        return
    if os.path.isfile(ci) or os.path.isfile(os.path.join(COVER_DIR, base)):
        book_info["cover_preview_url"] = (
            request_obj.host_url.rstrip("/") + "/api/cover/" + quote(base, safe="")
        )
