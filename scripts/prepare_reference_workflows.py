"""Prepare downloaded reference workflows for safe local inspection/import."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_ROOT = ROOT / "downloads" / "reference_workflows"
SENSITIVE_NAMES = {
    "api_key",
    "apikey",
    "api_token",
    "st_api_key",
    "hs_api_key",
    "mihe_key",
    "feishu_url",
    "attachment_token",
}
SITE = "https://member.laobaiai.top"


def _code_of(item) -> str:
    match = re.match(r"(G\d+)", str(item.get("name") or ""), re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _scrub_literals(value, sensitive_context: bool = False) -> int:
    changed = 0
    if isinstance(value, list):
        for item in value:
            changed += _scrub_literals(item, sensitive_context)
        return changed
    if not isinstance(value, dict):
        return changed

    name = str(value.get("name") or "").replace("-", "_").lower()
    current_sensitive = sensitive_context or name in SENSITIVE_NAMES
    for key, child in list(value.items()):
        key_sensitive = str(key).replace("-", "_").lower() in SENSITIVE_NAMES
        if current_sensitive and key == "content" and value.get("type") == "literal" and child not in (None, ""):
            value[key] = ""
            changed += 1
        else:
            changed += _scrub_literals(child, current_sensitive or key_sensitive)
    return changed


def prepare_category(category: str) -> dict:
    manifest_path = DOWNLOAD_ROOT / category / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public_items = requests.get(f"{SITE}/api/workflows", timeout=30).json().get("workflows", [])
    public_by_code = {_code_of(item): item for item in public_items if _code_of(item)}
    prepared = []
    for workflow in manifest.get("workflows", []):
        code = str(workflow.get("code") or "")
        public_item = public_by_code.get(code, {})
        if public_item:
            workflow["name"] = public_item.get("name") or workflow.get("name")
            workflow["description"] = public_item.get("description") or workflow.get("description")
            workflow["tags"] = sorted(
                str(tag.get("name") or "") if isinstance(tag, dict) else str(tag)
                for tag in (public_item.get("tags") or [])
                if tag
            )
            workflow["stats"] = {
                "views": int(public_item.get("views") or 0),
                "favorites": int(public_item.get("favorites") or 0),
                "downloads": int(public_item.get("downloads") or 0),
            }
            workflow["changelog"] = public_item.get("changelog")
            workflow["created_at"] = public_item.get("created_at")
            workflow["updated_at"] = public_item.get("updated_at")
        folder = DOWNLOAD_ROOT / category / code
        source = next(folder.glob("*工作流代码.txt"), None)
        if not source:
            prepared.append({"code": code, "error": "workflow source missing"})
            continue
        payload = json.loads(source.read_text(encoding="utf-8"))
        scrubbed = _scrub_literals(payload)
        destination = folder / "workflow.json"
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        prepared.append(
            {
                "code": code,
                "workflow_json": str(destination.relative_to(DOWNLOAD_ROOT)),
                "nodes": len((payload.get("json") or {}).get("nodes") or []),
                "scrubbed_literals": scrubbed,
            }
        )
        for file_info in workflow.get("files", []):
            file_info.pop("token", None)

    manifest["prepared"] = prepared
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"category": category, "prepared": prepared}


if __name__ == "__main__":
    requested = [
        category.strip()
        for category in os.environ.get("REFERENCE_CATEGORIES", "").split(",")
        if category.strip()
    ]
    if not requested:
        requested = [path.parent.name for path in DOWNLOAD_ROOT.glob("*/manifest.json")]
    print(json.dumps([prepare_category(category) for category in requested], ensure_ascii=False, indent=2))
