#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""综合书籍信息获取：百度百科 + 豆瓣 + Open Library 聚合。"""

import logging
import os
import re
import unicodedata
import requests

from config import HEADERS, CDN_TOKEN, setup_crawler_logging, is_hotlink_protected_url
from crawlers.baidu_baike import get_baidu_baike_info, _title_match_score
from crawlers.douban import crawl_douban_cover, fetch_douban_subject_author, fetch_douban_subject_summary
from crawlers.openlibrary import crawl_openlibrary_cover, fetch_openlibrary_primary_author, get_openlibrary_cover_url
from utils.cover import download_and_save_cover, upload_cover_to_cdn

_log = logging.getLogger("crawlers.book_info")


def _log_preview(text, max_len=80):
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text).strip())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _normalize_book_lookup(name):
    """书名比对键：NFKC、去空白与零宽字符，避免输入看似一致却匹配失败。"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name).strip())
    s = re.sub(r"[\s\u200b-\u200d\ufeff\u3000]+", "", s)
    return s


# 常见典籍作者（优先使用，不依赖外网 Open Library）
_RAW_KNOWN_BOOK_AUTHORS = (
    ("三国演义", "罗贯中"),
    ("三国志通俗演义", "罗贯中"),
    ("红楼梦", "曹雪芹"),
    ("石头记", "曹雪芹"),
    ("西游记", "吴承恩"),
    ("水浒传", "施耐庵"),
    ("聊斋志异", "蒲松龄"),
    ("儒林外史", "吴敬梓"),
    ("活着", "余华"),
    ("兄弟", "余华"),
    ("许三观卖血记", "余华"),
    ("在细雨中呼喊", "余华"),
    ("文城", "余华"),
    ("第七天", "余华"),
    ("我与地坛", "史铁生"),
    ("夜航船", "张岱"),
)
KNOWN_BOOK_AUTHORS = {
    _normalize_book_lookup(k): v for k, v in _RAW_KNOWN_BOOK_AUTHORS
}


def _attach_fetch_trace(book_info, trace):
    if trace is not None and book_info is not None:
        book_info["_fetch_trace"] = trace


def _book_title_has_cjk(name):
    return bool(name and re.search(r"[\u4e00-\u9fff]", str(name)))


def _author_looks_latin_only(author):
    if not author or not str(author).strip():
        return False
    s = str(author).strip()
    if re.search(r"[\u4e00-\u9fff]", s):
        return False
    return bool(re.search(r"[A-Za-z]", s))


def get_book_info(book_name, trace=None):
    """
    综合获取书籍信息。
    trace: 传入 list 则在 book_info 中附加 _fetch_trace；若为 None 且环境变量 CRAWLER_API_TRACE=1/true，则自动收集。
    """
    setup_crawler_logging()
    if trace is None and os.getenv("CRAWLER_API_TRACE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        trace = []
    session = requests.Session()
    session.headers.update(HEADERS)

    baike = get_baidu_baike_info(book_name, session=session, trace=trace)
    baike_failed = baike is None
    if trace is not None:
        trace.append(f"聚合: 百科 {'失败/无返回' if baike_failed else '成功'}")
    if baike_failed:
        _log.warning("百度百科 get_baidu_baike_info 返回 None: book_name=%r", book_name)
    result = baike or {
        "title": book_name,
        "author": "",
        "cover": "",
        "summary": "",
        "found": False,
        "message": "百度百科不可用或未找到词条，已尝试豆瓣/Open Library 补封面",
        "source": "",
    }

    useful = bool(
        (result.get("author") or "").strip()
        or (result.get("cover") or "").strip()
        or (result.get("summary") or "").strip()
    )

    # Baidu Baike 修改了 session headers（加了 Sec-Fetch-* 等），豆瓣/OL 需要干净 session
    douban_session = requests.Session()
    douban_session.headers.update(HEADERS)
    douban = crawl_douban_cover(book_name, session=douban_session)
    d_score = int(douban.get("score") or 0)
    if trace is not None:
        trace.append(
            f"聚合: 豆瓣 suggest score={d_score} has_url={bool(douban.get('url'))} "
            f"title={douban.get('title')!r}"
        )
    _log.debug(
        "豆瓣 suggest: has_url=%s score=%s title=%r",
        bool(douban.get("url")),
        d_score,
        douban.get("title"),
    )
    b_title_score = (
        0
        if baike_failed
        else _title_match_score(book_name, result.get("title") or "")
    )

    douban_headers = {**HEADERS, "Referer": "https://book.douban.com/"}
    prefer_douban = False
    if douban.get("url"):
        if d_score == 100:
            prefer_douban = True
        elif d_score >= 85 and b_title_score < 100:
            prefer_douban = True
        elif not (result.get("cover") or "").strip() and d_score >= 75:
            prefer_douban = True

    if prefer_douban:
        _log.info("封面策略: 优选豆瓣 (score=%s b_title_score=%s)", d_score, b_title_score)
        if trace is not None:
            trace.append(
                f"聚合: 封面优选豆瓣 (douban_score={d_score} b_title_match={b_title_score})"
            )
        local_d = download_and_save_cover(
            douban["url"], book_name, douban_session, extra_headers=douban_headers
        )
        if local_d:
            result["cover"] = local_d
            # 豆瓣图片域名反盗链（img*.doubanio.com 要求 Referer: book.douban.com），
            # Coze / 剪映草稿解析器下载时不带 Referer → 403，因此不能把豆瓣外链写进 cover_source_url。
            # 保留本地文件路径即可，下面的图床上传 / OL 兜底会补上真正可公网直取的 https URL。
            if not is_hotlink_protected_url(douban["url"]):
                result["cover_source_url"] = douban["url"]
            result["message"] = (result.get("message") or "已获取信息") + "；封面优选豆瓣"
            useful = True
        elif not (result.get("cover") or "").strip():
            # 下载都失败了就不再把反盗链外链塞给 Coze，直接留空等 OL 兜底
            if not is_hotlink_protected_url(douban["url"]):
                result["cover"] = douban["url"]
                result["message"] = (result.get("message") or "已获取信息") + "；封面来自豆瓣(外链)"
                useful = True

    # 若摘要为空，尝试从豆瓣条目页补充简介
    if not (result.get("summary") or "").strip() and douban.get("subject_url"):
        _db_summary = fetch_douban_subject_summary(douban["subject_url"], None)
        if _db_summary:
            result["summary"] = _db_summary

    # 如果有图床 Token，优先把本地封面上传到闪电图床，拿到真正公网 URL
    _cover_local = result.get("cover") or ""
    if CDN_TOKEN and _cover_local and not _cover_local.startswith(("http://", "https://")):
        _cdn_url = upload_cover_to_cdn(_cover_local, token=CDN_TOKEN)
        if _cdn_url:
            result["cover_source_url"] = _cdn_url

    # 若图床上传失败，尝试 OL 公网链作为备选。反盗链域名(豆瓣/百度)的 URL 也视同无效。
    _src = result.get("cover_source_url") or ""
    if not _src or not _src.startswith("https://") or is_hotlink_protected_url(_src):
        _ol = get_openlibrary_cover_url(book_name, result.get("author"), douban_session)
        if _ol:
            result["cover_source_url"] = _ol
        elif is_hotlink_protected_url(_src):
            # OL 没有也要清掉反盗链链接，避免 Coze 侧 403
            result["cover_source_url"] = ""

    if (
        not (result.get("author") or "").strip()
        and douban.get("subject_url")
        and d_score >= 75
    ):
        du_au = fetch_douban_subject_author(douban["subject_url"], session=douban_session)
        if du_au:
            result["author"] = du_au
            result["message"] = (result.get("message") or "已获取信息") + "；作者参考豆瓣条目"
            useful = True
            if trace is not None:
                trace.append(f"聚合: 豆瓣条目作者={du_au!r}")
            _log.info("豆瓣条目作者: %r", du_au)

    # 经典书目作者：百科/Open Library 可能误标（如丛书编者）；表内书名一律以本地为准并覆盖原 author
    kn = _normalize_book_lookup(book_name)
    if kn in KNOWN_BOOK_AUTHORS:
        correct = KNOWN_BOOK_AUTHORS[kn]
        prev = (result.get("author") or "").strip().rstrip("。．.")
        if prev != correct:
            result["author"] = correct
            if trace is not None:
                trace.append(
                    f"聚合: 经典书目表覆盖作者 {prev or '(空)'} -> {correct!r} (key={kn!r})"
                )
            _log.info(
                "经典书目表覆盖作者: book_key=%r prev=%r -> %r",
                kn,
                prev or "(空)",
                correct,
            )
            result["message"] = (result.get("message") or "已获取信息") + (
                "；作者以经典书目表为准（已覆盖不准确来源）" if prev else "；作者来自经典书目表"
            )
            useful = True

    if not (result.get("author") or "").strip():
        ol_author = fetch_openlibrary_primary_author(book_name, session=douban_session)
        if ol_author:
            if _book_title_has_cjk(book_name) and _author_looks_latin_only(ol_author):
                _log.info(
                    "未采用 Open Library 作者（中文书名 + 纯西文名，多为拼音误序）: %r",
                    ol_author,
                )
                if trace is not None:
                    trace.append(
                        f"聚合: 未采用 Open Library 作者 {ol_author!r}（中文书不采信纯西文名，可手填）"
                    )
            else:
                _log.info("Open Library 补作者: %r", ol_author)
                if trace is not None:
                    trace.append(f"聚合: Open Library 作者={ol_author!r}")
                result["author"] = ol_author
                result["message"] = (result.get("message") or "已获取信息") + "；作者参考 Open Library"
                useful = True

    if not (result.get("cover") or "").strip():
        extra_cover = crawl_openlibrary_cover(
            book_name, author=result.get("author"), session=douban_session
        )
        if extra_cover:
            result["cover"] = extra_cover
            result["message"] = (result.get("message") or "已获取信息") + "；封面由Open Library补全"
            useful = True
    if (result.get("cover") or "").strip() or (result.get("summary") or "").strip():
        result["found"] = True
    if useful:
        if not (result.get("author") or "").strip():
            result["message"] = (result.get("message") or "已从百度百科获取信息") + "；未识别到作者时可手动补充"
        if trace is not None:
            _auth_done = (result.get("author") or "").strip() or "(空)"
            trace.append(
                f"聚合: 结束 found={result.get('found')} author={_auth_done!r} "
                f"cover={'有' if (result.get('cover') or '').strip() else '无'}"
            )
        _attach_fetch_trace(result, trace)
        _log.info(
            "get_book_info 结束: found=%s author=%r cover=%s summary_len=%s msg=%s",
            result.get("found"),
            (result.get("author") or "").strip() or "(空)",
            "有" if (result.get("cover") or "").strip() else "无",
            len((result.get("summary") or "").strip()),
            _log_preview(result.get("message"), 80),
        )
        return result

    _log.warning("get_book_info 信息过少，返回空壳: book_name=%r", book_name)
    empty = {
        "title": result.get("title") or book_name,
        "author": "",
        "cover": "",
        "summary": "",
        "found": False,
        "message": "词条信息过少，请手动填写作者与封面",
        "source": result.get("source") or "",
    }
    _attach_fetch_trace(empty, trace)
    return empty
