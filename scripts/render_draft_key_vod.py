#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translate a draft_key and optionally submit it to Volcengine VOD."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.volcengine_vod_renderer import render_draft_key_vod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, required=True, help="Path to a draft_key JSON file")
    parser.add_argument("--submit", action="store_true", help="Submit the converted timeline to VOD")
    parser.add_argument("--wait", action="store_true", help="Wait for the submitted task to finish")
    parser.add_argument("--no-text", action="store_true", help="Exclude text tracks for schema isolation")
    parser.add_argument("--no-effects", action="store_true", help="Exclude effect tracks for schema isolation")
    parser.add_argument("--output-json", type=Path, help="Write the full result to this JSON file")
    args = parser.parse_args()

    key_path = args.key.resolve()
    key = json.loads(key_path.read_text(encoding="utf-8"))
    result = render_draft_key_vod(
        key,
        base_dir=key_path.parent,
        submit=args.submit,
        wait=args.wait,
        include_text=not args.no_text,
        include_effects=not args.no_effects,
    )
    if args.output_json:
        output = args.output_json.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "success": result.get("success"),
        "submitted": result.get("submitted"),
        "req_id": result.get("req_id"),
        "space": result.get("space"),
        "conversion": result.get("conversion"),
        "output_json": str(args.output_json.resolve()) if args.output_json else "",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
