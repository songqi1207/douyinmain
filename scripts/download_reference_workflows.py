"""下载指定业务类别或编号的参考工作流附件。

凭据只从环境变量读取，不写入仓库：
    $env:REFERENCE_SITE_USER = '...'
    $env:REFERENCE_SITE_PASSWORD = '...'
    $env:REFERENCE_WORKFLOW_CODES = 'G259,G258,G168,G45'
    python scripts/download_reference_workflows.py

每个飞书页面通常包含一份代码文本和一份剪映草稿 ZIP，都会保存到
``downloads/reference_workflows/<category>/<workflow-code>/``。
"""

import html as html_lib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests


SITE = "https://member.laobaiai.top"
FEISHU_FILE_URL = "https://my.feishu.cn/space/api/box/file/temporary_download_url/"
OUT = Path(__file__).resolve().parents[1] / "downloads" / "reference_workflows"
PREVIEW_OUT = Path(__file__).resolve().parents[1] / "static" / "workflow-previews"


def clean_name(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value).strip(" .")
    return value[:180] or "unnamed"


def tags_of(item):
    return {str(t.get("name", "")) if isinstance(t, dict) else str(t) for t in (item.get("tags") or [])}


def classify(item):
    name = str(item.get("name", ""))
    tags = tags_of(item)
    categories = []
    if "电商" in tags:
        categories.append("电商")
    if any(word in name for word in ("养生", "健康")):
        categories.append("养生")
    if "减肥" in name:
        categories.append("减肥")
    if "财经" in tags or any(word in name for word in ("财经", "金融", "股票", "基金", "理财", "商业模式", "经济")):
        categories.append("财经")
    # “起号”在对方站点没有显式标签，不在这里猜测归类。
    return categories


def code_of(item):
    match = re.match(r"(G\d+)", str(item.get("name", "")), re.IGNORECASE)
    return match.group(1).upper() if match else str(item.get("id"))[:8]


def extract_files(page_html: str):
    # SSR 的 block_map 会保留附件的完整 token、MIME、大小和名称。
    pattern = re.compile(
        r'"file":\{"token":"(?P<token>[^"]+)","mimeType":"(?P<mime>[^"]+)",'
        r'"size":(?P<size>\d+),"name":"(?P<name>[^"]+)"'
    )
    seen = set()
    for match in pattern.finditer(page_html):
        data = match.groupdict()
        if data["token"] in seen:
            continue
        seen.add(data["token"])
        data["name"] = html_lib.unescape(data["name"])
        data["size"] = int(data["size"])
        yield data


def download_attachment(session, token: str, destination: Path):
    response = session.post(FEISHU_FILE_URL, json={"file_token": token}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    url = ((payload.get("data") or {}).get("url") or "").strip()
    if not url:
        raise RuntimeError(f"temporary download URL unavailable: {payload}")
    with session.get(url, stream=True, timeout=(20, 180)) as stream:
        stream.raise_for_status()
        with destination.open("wb") as output:
            for chunk in stream.iter_content(1024 * 1024):
                if chunk:
                    output.write(chunk)
    return urlsplit(url).netloc


def download_url(session, url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=(20, 240)) as stream:
        stream.raise_for_status()
        with destination.open("wb") as output:
            for chunk in stream.iter_content(1024 * 1024):
                if chunk:
                    output.write(chunk)


def download_previews(session, item, category: str, code: str):
    uris = [str(item.get(key) or "").strip() for key in ("cover_url", "example_url")]
    uris = [uri for uri in uris if uri]
    if not uris:
        return []
    response = session.post(
        f"{SITE}/api/workflows/presign",
        json={"uris": uris, "thumbnail": False},
        timeout=30,
    )
    response.raise_for_status()
    urls = (response.json() or {}).get("urls") or {}
    records = []
    for index, uri in enumerate(uris):
        signed_url = str(urls.get(uri) or "").strip()
        if not signed_url:
            continue
        suffix = Path(urlsplit(uri).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"}:
            suffix = ".jpg" if index == 0 else ".mp4"
        destination = OUT / category / code / f"preview-{index + 1}{suffix}"
        download_url(session, signed_url, destination)
        records.append({"kind": "cover" if index == 0 else "example", "path": str(destination.relative_to(OUT))})
        if index == 0 and suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            catalog_cover = PREVIEW_OUT / category / f"{code}{suffix}"
            download_url(session, signed_url, catalog_cover)
    return records


def main():
    username = os.environ.get("REFERENCE_SITE_USER", "").strip()
    password = os.environ.get("REFERENCE_SITE_PASSWORD", "")
    if not username or not password:
        raise SystemExit("请先设置 REFERENCE_SITE_USER 和 REFERENCE_SITE_PASSWORD")

    session = requests.Session()
    login = session.post(
        f"{SITE}/api/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    login.raise_for_status()
    if not (login.json() or {}).get("success"):
        raise SystemExit("会员站登录失败")

    items = session.get(f"{SITE}/api/workflows", timeout=30).json().get("workflows", [])
    requested_codes = {
        code.strip().upper()
        for code in os.environ.get("REFERENCE_WORKFLOW_CODES", "").split(",")
        if code.strip()
    }
    if requested_codes:
        selected = {category: [] for category in ("电商", "养生", "减肥", "财经", "起号")}
        matched = [item for item in items if code_of(item) in requested_codes]
        for item in matched:
            categories = classify(item) or ["起号"]
            for category in categories:
                selected[category].append(item)
        selected = {category: workflows for category, workflows in selected.items() if workflows}
        found_codes = {code_of(item) for item in matched}
        missing_codes = sorted(requested_codes - found_codes)
        if missing_codes:
            raise SystemExit(f"未找到工作流：{','.join(missing_codes)}")
    else:
        selected = {category: [] for category in ("电商", "养生", "减肥", "起号")}
        for item in items:
            categories = classify(item)
            for category in categories:
                selected[category].append(item)

    OUT.mkdir(parents=True, exist_ok=True)
    summary_path = OUT / "manifest.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = {"source": SITE, "categories": {}}
    summary["source"] = SITE
    summary["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for category, workflows in selected.items():
        category_dir = OUT / category
        category_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for item in workflows:
            code = code_of(item)
            record = {
                "code": code,
                "name": item.get("name"),
                "description": item.get("description"),
                "tags": sorted(tags_of(item)),
                "stats": {
                    "views": int(item.get("views") or 0),
                    "favorites": int(item.get("favorites") or 0),
                    "downloads": int(item.get("downloads") or 0),
                },
                "changelog": item.get("changelog"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "source_url": item.get("download_url"),
                "files": [],
                "previews": [],
                "errors": [],
            }
            try:
                record["previews"] = download_previews(session, item, category, code)
                # 记录一次下载行为，确保页面权限与附件权限一致。
                session.post(f"{SITE}/api/workflows/{item['id']}/download", timeout=30).raise_for_status()
                page = session.get(item.get("download_url"), timeout=45)
                page.raise_for_status()
                files = list(extract_files(page.text))
                if not files:
                    raise RuntimeError("飞书页面未发现附件")
                target = category_dir / clean_name(code)
                target.mkdir(parents=True, exist_ok=True)
                for file_info in files:
                    filename = clean_name(file_info["name"])
                    destination = target / filename
                    host = download_attachment(session, file_info["token"], destination)
                    record["files"].append(
                        {
                            "name": file_info["name"],
                            "mime": file_info["mime"],
                            "size": file_info["size"],
                            "path": str(destination.relative_to(OUT)),
                            "host": host,
                        }
                    )
            except Exception as exc:  # 不中断其它类别，最后在 manifest 汇总失败项
                record["errors"].append(str(exc))
            records.append(record)
            print(category, code, "files", len(record["files"]), "errors", len(record["errors"]))
        manifest = {"category": category, "count": len(records), "workflows": records}
        (category_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["categories"][category] = {"count": len(records), "downloaded_files": sum(len(r["files"]) for r in records)}

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
