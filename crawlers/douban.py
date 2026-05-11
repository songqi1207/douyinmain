#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""豆瓣读书封面抓取。"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from config import HEADERS
from crawlers.baidu_baike import _title_match_score, _upgrade_douban_cover_url

_log = logging.getLogger("crawlers.douban")


def crawl_douban_cover(book_name, session=None):
    """
    豆瓣读书 subject_suggest，无需 key；国内图书封面匹配通常比百科配图更准。
    返回 {"url", "title", "score"} 或空 dict。
    """
    try:
        if not book_name or not str(book_name).strip():
            return {}
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)
        r = session.get(
            "https://book.douban.com/j/subject_suggest",
            params={"q": book_name.strip()},
            timeout=12,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        if not isinstance(data, list) or not data:
            return {}
        best = None
        best_score = -1
        for it in data:
            pic = (it.get("pic") or "").strip()
            sub_url = (it.get("url") or "").strip()
            if not pic or "/subject/" not in sub_url:
                continue
            tit = (it.get("title") or "").strip()
            sc = _title_match_score(book_name, tit)
            if sc > best_score:
                best_score = sc
                best = {"url": pic, "title": tit, "score": sc, "subject_url": sub_url}
        if not best or best_score <= 0:
            return {}
        best["url"] = _upgrade_douban_cover_url(best["url"])
        return best
    except Exception as e:
        _log.warning("豆瓣封面抓取失败: %s", e)
        return {}


def fetch_douban_subject_summary(subject_url, session=None):
    """
    从豆瓣图书条目页提取内容简介（#link-report 或 .intro 区域）。
    """
    try:
        if not subject_url or "/subject/" not in subject_url:
            return ""
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)
        headers = {**HEADERS, "Referer": "https://book.douban.com/"}
        r = session.get(subject_url, timeout=14, headers=headers)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        # 「内容简介」区域
        for div in soup.select("#link-report .intro, .related_info .intro"):
            text = div.get_text(separator="\n", strip=True)
            if len(text) > 30:
                return re.sub(r"\n{3,}", "\n\n", text)[:1500]
        return ""
    except Exception as e:
        _log.debug("豆瓣简介解析失败: %s", e)
        return ""


def fetch_douban_subject_author(subject_url, session=None):
    """
    从豆瓣图书条目页 #info 取「作者」后的第一链接文本（中文条目通常为中文名）。
    """
    try:
        if not subject_url or "/subject/" not in subject_url:
            return ""
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)
        headers = {**HEADERS, "Referer": "https://book.douban.com/"}
        r = session.get(subject_url, timeout=14, headers=headers)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        info = soup.select_one("#info")
        if not info:
            return ""
        for sp in info.select("span.pl"):
            label = re.sub(r"[\s\u3000]+", "", sp.get_text(strip=True))
            if not label.startswith("作者"):
                continue
            cur = sp.next_sibling
            while cur is not None:
                if getattr(cur, "name", None) == "a":
                    name = cur.get_text(strip=True)
                    if name and 2 <= len(name) <= 40:
                        return name
                if getattr(cur, "name", None) in ("span",):
                    a = cur.find("a")
                    if a:
                        name = a.get_text(strip=True)
                        if name and 2 <= len(name) <= 40:
                            return name
                cur = getattr(cur, "next_sibling", None)
            parent = sp.parent
            if parent:
                a = parent.find("a", href=re.compile(r"/author/|search"))
                if a:
                    name = a.get_text(strip=True)
                    if name and 2 <= len(name) <= 40:
                        return name
        return ""
    except Exception as e:
        _log.debug("豆瓣条目作者解析失败: %s", e)
        return ""
