#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""百度百科书籍信息爬虫。"""

import json
import logging
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from config import HEADERS, is_hotlink_protected_url
from utils.cover import download_and_save_cover

_log = logging.getLogger("crawlers.baidu_baike")


def _log_preview(text, max_len=120):
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text).strip())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _normalize_book_title(s):
    """书名比较：去空白，便于「三 体」与「三体」一致。"""
    if not s:
        return ""
    return re.sub(r"\s+", "", str(s).strip())


def _title_match_score(query, candidate_title):
    q = _normalize_book_title(query)
    c = _normalize_book_title(candidate_title)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if q in c:
        return 85
    if c in q:
        return 75
    return 0


def _bkimg_area_from_url(url):
    """百度百科图床 URL 中带 @w,h 时估算面积，越大越可能是主图。"""
    if not url:
        return 0
    m = re.search(r"@w_(\d+),h_(\d+)", url)
    if m:
        return int(m.group(1)) * int(m.group(2))
    if "bkimg.cdn.bcebos.com" in url and "@w_" not in url:
        return 10_000_000
    return 0


def _upgrade_douban_cover_url(url):
    """豆瓣 subject_suggest 返回多为 s/public 小图，换 l/public 大图。"""
    if not url:
        return url
    u = url.replace("/subject/s/public/", "/subject/l/public/")
    u = u.replace("/view/subject/s/public/", "/view/subject/l/public/")
    return u


def _normalize_basic_label(text):
    """百科基本信息 dt 标签：去掉空白、全角空格、&nbsp;，便于匹配「作　者」「作 者」等。"""
    if not text:
        return ""
    t = str(text).replace("&nbsp;", "").replace("&#160;", "")
    t = re.sub(r"[\s\u3000\xa0]+", "", t.strip())
    return t


def _basic_info_dd_for_dt(dt):
    """同一栏的 dd：dt 紧邻兄弟，或在同一 itemWrapper 容器内。"""
    if not dt:
        return None
    dd = dt.find_next_sibling("dd")
    if dd:
        return dd
    parent = dt.parent
    if parent:
        for sib in getattr(parent, "children", []):
            if getattr(sib, "name", None) == "dd":
                return sib
    return None


def _author_value_from_dd(dd):
    """
    从 dd 取作者：优先带 /item/ 的内链作者名（新版 basicInfo innerLink），
    避免 get_text 把角标 [3] 等并入。
    """
    if not dd:
        return ""
    for a in dd.select('a[href*="/item/"]'):
        t = a.get_text(strip=True)
        t = re.sub(r"\s+", "", t)
        if (
            t
            and 2 <= len(t) <= 40
            and t not in ("编辑", "引用日期")
            and (re.search(r"[\u4e00-\u9fff]", t) or re.fullmatch(r"[A-Za-z][A-Za-z·.\-\s]{1,38}", t))
        ):
            return t
    val = dd.get_text(separator="", strip=True)
    val = re.sub(r"\[[\d\s,，]+\]", "", val)
    val = re.split(r"[\n、，,/／|]", val)[0].strip()
    val = re.sub(r"\s+", "", val)
    if val and len(val) >= 2 and len(val) <= 40:
        return val
    return ""


def _extract_author_from_basic_info(soup):
    """
    从百科「基本信息栏」取作者：老版 dl.basicInfo-block dt/dd，
    新版 div.itemWrapper_* / dt.basicInfoItem_*（如「作&nbsp;者」）+ dd.itemValue_*。
    """
    if not soup:
        return ""
    author_labels = (
        "作者",
        "文学作者",
        "原著作者",
        "原作者",
        "撰著者",
        "编著",
        "著者",
    )
    dts = soup.select("dl.basicInfo-block dt")
    if not dts:
        dts = soup.select('div[class*="itemWrapper"] dt')
    if not dts:
        dts = soup.find_all("dt")
    seen_dt = set()
    for dt in dts:
        if id(dt) in seen_dt:
            continue
        seen_dt.add(id(dt))
        label = _normalize_basic_label(dt.get_text())
        if label not in author_labels:
            continue
        dd = _basic_info_dd_for_dt(dt)
        if not dd:
            continue
        val = _author_value_from_dd(dd)
        if val:
            return val
    return ""


def _extract_author_from_raw_html(html):
    """从页面内嵌 JSON / 片段中抽作者（SPA 或分段下发时常带字段）。"""
    if not html:
        return ""
    patterns = [
        r'"authorName"\s*:\s*"([^"]{2,40})"',
        r'"作者"\s*:\s*"([^"]{2,40})"',
        r'"author"\s*:\s*"([\u4e00-\u9fff·\w]{2,24})"',
    ]
    exclude = {"编辑", "出版社", "undefined", "null"}
    for pat in patterns:
        m = re.search(pat, html)
        if not m:
            continue
        s = m.group(1).strip()
        if s in exclude or len(s) < 2:
            continue
        return s
    return ""


def _lemma_desc_text_from_dom(soup):
    """
    新版百科摘要区结构（CSS Modules 后缀会变，稳定锚点如下）：
    <div id="lemmaDesc" class="lemmaDesc_XXX">
      <div class="lemmaDescText_XXX">余华著长篇小说</div>
      <div class="polysemantText_XXX">…同名词条…</div>
    </div>
    必须落在 #lemmaDesc 内的 lemmaDescText，避免扫到页面别处同名 class，且不采「同名词条」消歧块。
    """
    if not soup:
        return ""

    def _clean_desc_text(t):
        t = (t or "").strip()
        if not t or "同名词条" in t:
            return ""
        return t

    root = soup.select_one("#lemmaDesc")
    if root:
        for el in root.select('[class*="lemmaDescText"]'):
            t = _clean_desc_text(el.get_text(separator="", strip=True))
            if t:
                return t

    for el in soup.select('[class*="lemmaDescText"]'):
        if el.find_parent(id="lemmaDesc") is None and soup.select_one("#lemmaDesc"):
            continue
        t = _clean_desc_text(el.get_text(separator="", strip=True))
        if t:
            return t
    return ""


def _extract_author_before_zhu_phrase(lemma_desc, exclude_words):
    """
    匹配百科常见結尾「罗贯中著长篇小说」：作者名紧贴「著×篇小说」之前，
    按 3→2→4 字切尾部（优先三名），避免正则从左向右滑动误吞「初罗贯中」等。
    """
    if not lemma_desc:
        return ""
    for phrase in ("著长篇小说", "著中篇小说", "著短篇小说"):
        i = lemma_desc.find(phrase)
        if i < 2:
            continue
        for L in (3, 2, 4):
            if i < L:
                continue
            cand = lemma_desc[i - L : i]
            if re.fullmatch(r"[\u4e00-\u9fff·]{2,4}", cand) and cand not in exclude_words:
                return cand
    return ""


def _extract_author_from_lemma_desc(lemma_desc):
    """从 lemmaDesc / 摘要文案中用多种句式抽作者。"""
    if not lemma_desc:
        return ""
    exclude_words = {
        "清代", "明代", "现代", "古代", "中国", "著名", "小说", "该书", "系列", "长篇", "短篇",
        "一部", "一本", "这篇", "这本", "该书",
    }
    au = _extract_author_before_zhu_phrase(lemma_desc, exclude_words)
    if au:
        return au
    # 须放在泛化「X著」之前；泛化仍可能多命中，下面按每次匹配的最后一次过滤
    author_patterns = [
        r"([\u4e00-\u9fff·]{2,4})著(?:诗集|诗文|文集|诗选|词集|散文集|杂文集)",
        r"作家([^\s，。]{2,20}?)[所著撰写]",
        r"由([\u4e00-\u9fff·•．.\w]{2,20}?)(?:所著|撰写|编著|创作|编写|所作)",
        r"《[^》]{1,40}》是([\u4e00-\u9fff·•．.\w]{2,20}?)(?:所著|撰写|创作|编写|的)",
        r"作者是[:：]?\s*([\u4e00-\u9fff·•．.\w]{2,20}?)(?:[,，。\s]|所著|$)",
        r"作者[:：]\s*([\u4e00-\u9fff·•．.\w]{2,20}?)(?:[,，。\s]|著|$)",
        r"原著[:：]\s*([\u4e00-\u9fff]{2,12})(?:著|编|写|，|。|$)",
        r"([\u4e00-\u9fff·•．.\w]{2,12})创作的",
        r"([\u4e00-\u9fff·•．.\w]{2,12})著(?:有|作)?",
    ]
    for pattern in author_patterns:
        matches = list(re.finditer(pattern, lemma_desc))
        if not matches:
            continue
        for match in reversed(matches):
            author = match.group(1).strip()
            author = re.sub(r"[（(].*?[）)]", "", author).strip()
            if author in exclude_words or len(author) < 2:
                continue
            return author
    return ""


def _collect_baidu_bkimg_urls(soup, html_text):
    """收集百科页可能的封面图 URL，按尺寸优先排序。"""
    found = set()

    def add(u):
        if not u or u in found:
            return
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        if "bkimg.cdn.bcebos.com" not in u:
            return
        low = u.lower()
        if any(x in low for x in ("logo", "icon", "avatar", "badge", "qr", "emotion")):
            return
        found.add(u)

    if soup:
        og = soup.select_one('meta[property="og:image"]')
        if og and og.get("content"):
            add(og["content"])
        for img in soup.select("img"):
            for attr in ("data-src", "data-original", "src"):
                v = img.get(attr)
                if v:
                    add(v)
    if html_text:
        for m in re.finditer(
            r"https?://bkimg\.cdn\.bcebos\.com/[^\"'\\s<>]+", html_text
        ):
            add(m.group(0))

    urls = list(found)
    urls.sort(key=_bkimg_area_from_url, reverse=True)
    return urls


def _trace_append(trace, msg):
    if trace is not None:
        trace.append(msg)


def get_baidu_baike_info(book_name, session=None, trace=None):
    """
    从百度百科获取书籍信息
    trace: 若传入 list，会写入简要步骤（与日志对应，便于在 API JSON 里展示）。
    """
    author_source = ""
    try:
        if session is None:
            session = requests.Session()
            session.headers.update(HEADERS)

        _BAIKE_HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        session.headers.update(_BAIKE_HEADERS)

        # 先访问百度主站拿 Cookie，再访问百科
        try:
            session.get("https://www.baidu.com", timeout=8)
        except Exception:
            pass
        session.headers["Referer"] = "https://www.baidu.com/s?wd=" + quote(book_name)

        # 直接访问词条URL
        baike_url = f"https://baike.baidu.com/item/{quote(book_name)}"
        _trace_append(trace, f"百科: GET {baike_url}")
        _log.info("请求词条 URL: %s", baike_url)
        resp = session.get(baike_url, timeout=15, allow_redirects=True)
        resp.encoding = 'utf-8'
        final_u = getattr(resp, "url", "") or baike_url
        _trace_append(trace, f"百科: HTTP {resp.status_code} final_url={final_u}")
        _log.info("HTTP 状态: %s final_url=%s", resp.status_code, final_u)

        if resp.status_code != 200:
            _trace_append(trace, "百科: 非 200，未解析 HTML（作者/摘要为空）")
            _log.warning("非 200，放弃解析: book_name=%r", book_name)
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 初始化结果
        result = {
            "title": book_name,
            "author": "",
            "cover": "",
            "summary": "",
            "found": True,
            "message": "已从百度百科获取信息",
            "source": "百度百科"
        }

        # 提取标题
        title_elem = soup.select_one('h1')
        if title_elem:
            title_text = title_elem.get_text(strip=True)
            title_text = re.sub(r'\[.*?\]', '', title_text).strip()
            if title_text:
                result["title"] = title_text

        # 从 PAGE_DATA JSON 提取描述
        start_idx = resp.text.find('PAGE_DATA=')
        page_data_ok = False
        lemma_from_page_data = ""
        au_page_data = ""
        if start_idx != -1:
            json_start = start_idx + len('PAGE_DATA=')
            brace_count = 0
            json_end = json_start
            for i, c in enumerate(resp.text[json_start:], json_start):
                if c == '{':
                    brace_count += 1
                elif c == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break

            json_str = resp.text[json_start:json_end]
            try:
                page_data = json.loads(json_str)
                page_data_ok = True
                lemma_desc = (
                    page_data.get("lemmaDesc")
                    or page_data.get("lemmaSummary")
                    or page_data.get("abstract")
                    or ""
                )
                if isinstance(lemma_desc, dict):
                    lemma_desc = str(lemma_desc.get("text") or lemma_desc.get("content") or "")
                lemma_from_page_data = str(lemma_desc).strip() if lemma_desc else ""
                if lemma_from_page_data:
                    result["summary"] = lemma_from_page_data
                    au_page_data = _extract_author_from_lemma_desc(lemma_from_page_data)
                    if au_page_data:
                        result["author"] = au_page_data
                        author_source = "PAGE_DATA(lemmaDesc/summary/abstract)"

                if page_data.get('lemmaTitle'):
                    result["title"] = page_data['lemmaTitle']
            except Exception as e:
                _trace_append(trace, f"百科: PAGE_DATA 解析失败 {e}")
                _log.warning("PAGE_DATA JSON 解析失败: %s", e)
        _trace_append(
            trace,
            f"百科: PAGE_DATA offset={start_idx} parsed={page_data_ok} "
            f"summary_len={len(lemma_from_page_data)} author_from_data={au_page_data or '(空)'}",
        )
        _log.debug(
            "PAGE_DATA: offset=%s parsed=%s summary_len=%s author=%r preview=%r",
            start_idx,
            page_data_ok,
            len(lemma_from_page_data),
            au_page_data or "",
            _log_preview(lemma_from_page_data, 160),
        )

        # 新版页面：摘要区 DOM（稳定锚点 #lemmaDesc > .lemmaDescText_*）
        has_lemma_desc_node = bool(soup.select_one("#lemmaDesc"))
        dom_lemma = _lemma_desc_text_from_dom(soup)
        _log.debug(
            "#lemmaDesc 节点存在=%s DOM 摘要 len=%s preview=%r",
            has_lemma_desc_node,
            len(dom_lemma or ""),
            _log_preview(dom_lemma, 160),
        )
        if dom_lemma:
            if not (result.get("summary") or "").strip():
                result["summary"] = dom_lemma
            # 词条首行「某某著长篇小说」与 #lemmaDesc 内文案一致时，优先于 PAGE_DATA/基本信息栏（后者常误标丛书编者）
            _trace_append(
                trace,
                f"百科: #lemmaDesc 存在={has_lemma_desc_node} DOM摘要预览={_log_preview(dom_lemma, 80)}",
            )
            au_dom = _extract_author_from_lemma_desc(dom_lemma)
            if au_dom:
                zhu_tail = bool(re.search(r"著(?:长|中|短)篇小说\s*$", dom_lemma.strip()))
                if zhu_tail:
                    result["author"] = au_dom
                    author_source = "DOM(#lemmaDesc) 著长篇小说 优先覆盖"
                elif not result["author"]:
                    result["author"] = au_dom
                    author_source = "DOM(#lemmaDesc) 摘要补作者"
                _trace_append(
                    trace,
                    f"百科: 从 DOM 摘要抽作者={au_dom!r} 著长篇小说句尾={zhu_tail}",
                )
                _log.debug(
                    "从 DOM 摘要抽作者: %r zhu_tail=%s (PAGE_DATA 曾给作者=%r)",
                    au_dom,
                    zhu_tail,
                    au_page_data or "",
                )

        # 基本信息栏「作者」（DOM/摘要未识别时）
        if not result["author"]:
            au_bi = _extract_author_from_basic_info(soup)
            if au_bi:
                result["author"] = au_bi
                author_source = "基本信息栏 dt/dd"
                _trace_append(trace, f"百科: 基本信息栏作者={au_bi!r}")
                _log.debug("基本信息栏作者: %r", au_bi)

        # 内嵌 JSON / 字段片段
        if not result["author"]:
            au_raw = _extract_author_from_raw_html(resp.text)
            if au_raw:
                result["author"] = au_raw
                author_source = "页面内嵌 JSON/HTML 片段"
                _trace_append(trace, f"百科: 内嵌字段 author={au_raw!r}")
                _log.debug("raw_html 字段作者: %r", au_raw)

        # 如果没获取到作者，尝试从页面中匹配著名作家
        if not result["author"]:
            page_text = soup.get_text()
            famous_authors = ['曹雪芹', '罗贯中', '吴承恩', '施耐庵', '鲁迅', '巴金', '茅盾',
                              '老舍', '沈从文', '钱钟书', '史铁生', '余华', '莫言', '刘慈欣', '王朔',
                              '金庸', '古龙', '梁羽生', '琼瑶', '三毛', '海子', '顾城',
                              '张爱玲', '萧红', '马尔克斯', '托尔斯泰', '陀思妥耶夫斯基',
                              '莎士比亚', '狄更斯', '雨果', '巴尔扎克', '海明威', '卡夫卡',
                              '川端康成', '村上春树', '东野圭吾', '泰戈尔', '契诃夫', '莫泊桑']

            for author in famous_authors:
                if author in page_text:
                    result["author"] = author
                    author_source = f"正文含名家名: {author}"
                    break
            if result["author"]:
                _trace_append(trace, f"百科: 正文名家名命中 author={result['author']!r}")
                _log.debug("名家表命中: %r", result["author"])
            else:
                _trace_append(trace, "百科: 未从 PAGE_DATA/DOM/基本信息栏/内嵌字段/名家表得到作者")

        # 获取封面图片（多候选 + 懒加载属性 + 正文中的 bkimg 链接，取最大尺寸主图）
        cover_candidates = _collect_baidu_bkimg_urls(soup, resp.text)
        _log.debug("bkimg 封面候选数=%s top=%r", len(cover_candidates), cover_candidates[:1])
        if cover_candidates:
            cover_url = cover_candidates[0]
            img_headers = {
                **HEADERS,
                "Referer": "https://baike.baidu.com/",
            }
            local_url = download_and_save_cover(
                cover_url, book_name, session, extra_headers=img_headers
            )
            if local_url:
                result["cover"] = local_url
                # bkimg 域名反盗链，Coze 侧拉不动；只有非反盗链域名才保留为公网源链
                if not is_hotlink_protected_url(cover_url):
                    result["cover_source_url"] = cover_url
            else:
                # 下载失败又是反盗链域名，放弃；避免后续给 Coze 一个 403 链接
                if not is_hotlink_protected_url(cover_url):
                    result["cover"] = cover_url
            _log.info("封面: 选用 %s", _log_preview(result.get("cover") or cover_url, 100))

        _trace_append(
            trace,
            f"百科: 汇总 title={result.get('title')!r} author={result.get('author')!r} "
            f"source={author_source or '(无)'} summary_len={len((result.get('summary') or '').strip())} "
            f"cover={'有' if (result.get('cover') or '').strip() else '无'}",
        )
        _log.info(
            "百科汇总: title=%r author=%r source=%s summary_len=%s",
            result.get("title"),
            result.get("author"),
            author_source or ("(无)" if not result.get("author") else "未单独标记"),
            len((result.get("summary") or "").strip()),
        )
        return result

    except Exception as e:
        _trace_append(trace, f"百科: 异常 {e}")
        _log.exception("百度百科爬取失败: %s", e)
        return None
