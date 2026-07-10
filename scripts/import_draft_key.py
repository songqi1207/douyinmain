#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Coze 工作流输出的 key 数据包导入为本地剪映草稿。

用法:
    python scripts/import_draft_key.py key.json
    python scripts/import_draft_key.py key.json --force      # 删除同 key 旧草稿后重导
    python scripts/import_draft_key.py key.json --dry-run    # 只校验并列出计划，不落盘
    python scripts/import_draft_key.py --stdin < key.json    # 从标准输入读 key

退出码: 0 成功 / 2 key 校验失败 / 3 素材下载失败 / 1 其他错误
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.draft_key_importer import (  # noqa: E402
    AssetDownloadError,
    KeyValidationError,
    import_draft_key,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="key 数据包 → 本地剪映草稿")
    parser.add_argument("key_file", nargs="?", help="key JSON 文件路径")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取 key JSON")
    parser.add_argument("--force", action="store_true", help="同 key 已导入过时删除旧草稿重导")
    parser.add_argument("--dry-run", action="store_true", help="只校验 key 并输出执行计划")
    args = parser.parse_args()

    if args.stdin:
        raw = sys.stdin.read()
    elif args.key_file:
        raw = Path(args.key_file).read_text(encoding="utf-8-sig")
    else:
        parser.error("需要 key 文件路径或 --stdin")
        return 1

    try:
        key = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"key 不是合法 JSON: {exc}", file=sys.stderr)
        return 2

    try:
        report = import_draft_key(key, force=args.force, dry_run=args.dry_run)
    except KeyValidationError as exc:
        print("key 校验失败:", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    except AssetDownloadError as exc:
        print("素材下载失败:", file=sys.stderr)
        for url, reason in exc.failed.items():
            print(f"  - {url}: {reason}", file=sys.stderr)
        return 3

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("warnings"):
        print("\n注意以下告警:", file=sys.stderr)
        for warning in report["warnings"]:
            print(f"  - {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
