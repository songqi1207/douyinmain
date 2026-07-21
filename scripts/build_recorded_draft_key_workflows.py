#!/usr/bin/env python3
"""Build three Mihe workflows that also return a portable draft_key sidecar."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.draft_key_recorder import add_draft_key_recorder


PROFILES = (
    {
        "source": ROOT / "书单工作流模板_荐书-v1.json",
        "output": ROOT / "书单工作流模板_荐书-draft_key-v1.json",
        "workflow_name": "书单工作流_米核插件+draft_key记录",
        "draft_name": "书单_本地草稿",
        "run_prefix": "book_recorded_",
    },
    {
        # 香烟必须使用最初可正常连线的中华母版；旧的静态
        # 烟工作流模板_香烟鉴赏-v1.json 是误用神模板派生出的版本。
        "source": ROOT / "每天认识一款香烟_中华_20260708_121403.txt",
        "output": ROOT / "烟工作流模板_香烟鉴赏-draft_key-v1.json",
        "workflow_name": "香烟工作流_米核插件+draft_key记录",
        "draft_name": "香烟_本地草稿",
        "run_prefix": "cigarette_recorded_",
    },
    {
        "source": ROOT / "神工作流模板_修改版-开场静态修正-v7.json",
        "output": ROOT / "神工作流模板_修改版-开场静态修正-draft_key-v1.json",
        "workflow_name": "神工作流_米核插件+draft_key记录",
        "draft_name": "神话解说_本地草稿",
        "run_prefix": "god_recorded_",
    },
)


def build_all() -> list[dict]:
    reports = []
    for profile in PROFILES:
        workflow = json.loads(profile["source"].read_text(encoding="utf-8"))
        report = add_draft_key_recorder(
            workflow,
            workflow_name=profile["workflow_name"],
            draft_name=profile["draft_name"],
            run_prefix=profile["run_prefix"],
        )
        profile["output"].write_text(
            json.dumps(workflow, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        reports.append(
            {
                "source": str(profile["source"]),
                "output": str(profile["output"]),
                "calls": len(report["calls"]),
                "recorder_nodes": report["recorder_node_count"],
            }
        )
    return reports


if __name__ == "__main__":
    print(json.dumps(build_all(), ensure_ascii=False, indent=2))
