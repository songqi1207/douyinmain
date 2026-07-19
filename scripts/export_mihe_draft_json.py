#!/usr/bin/env python3
"""Export Mihe's untouched server draft JSON and a navigable structure index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_bridge.mihe_direct import MiheDirectError, export_mihe_server_draft_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出米核服务器原始草稿 JSON 和结构索引")
    parser.add_argument("draft_id", help="扣子工作流返回的米核 UUID v4 草稿 ID")
    parser.add_argument("--output-dir", help="输出目录；默认 temp/mihe_draft_exports/<draft_id>")
    args = parser.parse_args(argv)
    output_dir = (
        Path(args.output_dir).expanduser()
        if args.output_dir
        else ROOT / "temp" / "mihe_draft_exports" / args.draft_id.strip()
    )
    try:
        report = export_mihe_server_draft_json(args.draft_id, output_dir=output_dir)
    except MiheDirectError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
