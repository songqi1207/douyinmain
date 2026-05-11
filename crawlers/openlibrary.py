#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Open Library 封面抓取（百度无封面时兜底）。"""

import requests

from config import HEADERS
from crawlers.baidu_baike import _title_match_score
from utils.cover import download_and_save_cover


def fetch_openlibrary_primary_author(book_name, session=None):
    """
    百科未写出作者时，用 Open Library 检索结果中匹配度最高条目的作者名兜底。
    """
    try:
        if not book_name or not str(book_name).strip():
            return ""
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)

        search_url = "https://openlibrary.org/search.json"
        bt = book_name.strip()
        params = {"limit": 12, "q": f"title:{bt}"}
        resp = session.get(search_url, params=params, timeout=12)
        if resp.status_code != 200 or not (resp.json() or {}).get("docs"):
            resp = session.get(
                search_url,
                params={"title": book_name, "limit": 12},
                timeout=12,
            )
        if resp.status_code != 200:
            return ""
        data = resp.json() or {}
        docs = data.get("docs") or []
        if not docs:
            return ""

        def score_doc(doc):
            title = str(doc.get("title") or "")
            publish_year = doc.get("first_publish_year") or 0
            score = _title_match_score(book_name, title)
            if not score:
                if book_name in title:
                    score = 60
                elif title and title in book_name:
                    score = 50
            if doc.get("cover_i"):
                score += 25
            if publish_year:
                score += 2
            return score

        docs = sorted(docs, key=score_doc, reverse=True)
        best = docs[0]
        names = best.get("author_name") or []
        if isinstance(names, list) and names:
            return str(names[0] or "").strip()
        return ""
    except Exception as e:
        print(f"OpenLibrary作者抓取失败: {e}")
        return ""


def get_openlibrary_cover_url(book_name, author=None, session=None):
    """
    仅返回 Open Library 封面的公网 URL，不下载到本地。
    covers.openlibrary.org 无防盗链，Coze 服务端可直接访问。
    """
    try:
        if not book_name:
            return ""
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)

        search_url = "https://openlibrary.org/search.json"
        bt = book_name.strip()
        au = (str(author).strip() if author else "")
        params = {"limit": 12, "q": (f"title:{bt} author:{au}" if au else f"title:{bt}")}
        resp = session.get(search_url, params=params, timeout=10)
        if resp.status_code != 200 or not (resp.json() or {}).get("docs"):
            resp = session.get(search_url, params={"title": book_name, "limit": 12}, timeout=10)
        if resp.status_code != 200:
            return ""
        docs = (resp.json() or {}).get("docs") or []
        docs = sorted(
            docs,
            key=lambda d: (
                _title_match_score(book_name, str(d.get("title") or "")) * 10
                + (25 if d.get("cover_i") else 0)
            ),
            reverse=True,
        )
        for doc in docs:
            cover_i = doc.get("cover_i")
            if not cover_i:
                continue
            ol_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
            try:
                r = session.get(ol_url, allow_redirects=True, timeout=10)
                # 跟随跳转后的最终 URL（archive.org 等）；若是占位 1x1 图则跳过
                if r.status_code == 200 and len(r.content) > 2048:
                    return r.url
            except Exception:
                pass
        return ""
    except Exception:
        return ""


def crawl_openlibrary_cover(book_name, author=None, session=None):
    """
    从 Open Library 检索封面（百度无封面时兜底）。
    """
    try:
        if not book_name:
            return ""
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)

        search_url = "https://openlibrary.org/search.json"
        bt = book_name.strip()
        au = (str(author).strip() if author else "")
        params = {"limit": 12, "q": (f"title:{bt} author:{au}" if au else f"title:{bt}")}
        resp = session.get(search_url, params=params, timeout=12)
        if resp.status_code != 200 or not (resp.json() or {}).get("docs"):
            resp = session.get(
                search_url,
                params={"title": book_name, "limit": 12},
                timeout=12,
            )
        if resp.status_code != 200:
            return ""
        data = resp.json() or {}
        docs = data.get("docs") or []
        if not docs:
            return ""

        def score_doc(doc):
            title = str(doc.get("title") or "")
            publish_year = doc.get("first_publish_year") or 0
            score = _title_match_score(book_name, title)
            if not score:
                if book_name in title:
                    score = 60
                elif title and title in book_name:
                    score = 50
            if doc.get("cover_i"):
                score += 25
            if publish_year:
                score += 2
            if author and str(author).strip():
                an = str(author).strip()
                authors = doc.get("author_name") or []
                if isinstance(authors, list) and any(an in (a or "") for a in authors):
                    score += 15
            return score

        docs = sorted(docs, key=score_doc, reverse=True)
        ol_headers = {**HEADERS, "Referer": "https://openlibrary.org/"}
        for doc in docs:
            cover_i = doc.get("cover_i")
            if not cover_i:
                continue
            cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
            local_url = download_and_save_cover(
                cover_url, book_name, session, extra_headers=ol_headers
            )
            return local_url or cover_url
        return ""
    except Exception as e:
        print(f"OpenLibrary封面抓取失败: {e}")
        return ""
