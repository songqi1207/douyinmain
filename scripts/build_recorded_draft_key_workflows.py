#!/usr/bin/env python3
"""Build three Mihe workflows that also return a portable draft_key sidecar."""

from __future__ import annotations

import copy
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


def ensure_book_batch_inputs(workflow: dict) -> None:
    """Keep the three book TTS batch lists non-empty at runtime.

    The remote text splitter can complete without producing ``segments``.  A
    downstream fallback is not enough in that case because Coze may skip that
    whole branch.  Replace the splitter dependency with deterministic local
    splitting of the LLM's raw narration.
    """
    graph = workflow.get("json") or {}
    graph["nodes"] = [
        node
        for node in (graph.get("nodes") or [])
        if str(node.get("id")) != "152468"
    ]
    graph["edges"] = [
        edge
        for edge in (graph.get("edges") or [])
        if str(edge.get("sourceNodeID")) != "152468"
        and str(edge.get("targetNodeID")) != "152468"
    ]
    direct_edge = {"sourceNodeID": "157315", "targetNodeID": "114310"}
    if not any(
        str(edge.get("sourceNodeID")) == direct_edge["sourceNodeID"]
        and str(edge.get("targetNodeID")) == direct_edge["targetNodeID"]
        for edge in graph["edges"]
    ):
        graph["edges"].append(direct_edge)

    nodes = {
        str(node.get("id")): node
        for node in graph["nodes"]
    }
    normalizer = nodes.get("114310")
    if normalizer is None:
        raise ValueError("书单模板缺少文案归一化节点 114310")

    inputs = (normalizer.get("data") or {}).setdefault("inputs", {})
    parameters = inputs.setdefault("inputParameters", [])
    parameters[:] = [
        parameter
        for parameter in parameters
        if str(parameter.get("name") or "") not in {"wenan", "raw_wenan"}
    ]
    parameters.append(
        {
            "name": "wenan",
            "input": {
                "type": "string",
                "value": {
                    "type": "ref",
                    "content": {
                        "source": "block-output",
                        "blockID": "157315",
                        "name": "wenan",
                    },
                    "rawMeta": {"type": 1},
                },
            },
        }
    )
    inputs["code"] = r"""
import re


def _is_readable(value):
    return bool(re.search(r'[A-Za-z0-9\u4e00-\u9fff]', str(value or '')))


def _non_empty_segments(value):
    if isinstance(value, (list, tuple)):
        result = [str(item or '').strip() for item in value]
        return [item for item in result if item and _is_readable(item)]

    text = str(value or '').strip()
    if not text or not _is_readable(text):
        return []
    result = [
        item.strip()
        for item in re.findall(r'[^。！？!?\n]+[。！？!?]?', text)
        if item.strip() and _is_readable(item)
    ]
    return result or [text]


async def main(args: Args) -> Output:
    params = args.params
    subject = str(params.get('subject') or '').strip()
    if not _is_readable(subject):
        subject = '一本好书'
    intro = str(params.get('kc_wenan') or '').strip()
    if not _is_readable(intro):
        intro = '今天我们要讲的是'
    body = _non_empty_segments(params.get('wenan'))
    if not body:
        body = [subject]

    return {
        'kc_wenan': [intro],
        'subject_wenan': [subject],
        'zw_wenan': body,
    }
""".strip()
    inputs["language"] = 3

    collector_sources = {
        "150200": ("154758", "正文配音", "zw_wenan"),
        "152457": ("1351770", "开场配音", "kc_wenan"),
        "181955": ("1033952", "书名配音", "subject_wenan"),
    }
    collector_code = r"""
def _message(row, index, label, texts):
    source_text = ''
    if isinstance(texts, list) and index < len(texts):
        source_text = str(texts[index] or '').strip()
    preview = source_text[:80] if source_text else '<空>'
    if not isinstance(row, dict):
        return '{}第{}项返回格式异常，原文={}'.format(label, index + 1, preview)
    code = row.get('code')
    message = str(row.get('msg') or row.get('message') or '').strip()
    if message:
        return '{}第{}项 code={}，原文={}：{}'.format(
            label, index + 1, code, preview, message
        )
    return '{}第{}项 code={}，原文={}：未返回音频 data.link'.format(
        label, index + 1, code, preview
    )


async def main(args: Args) -> Output:
    rows = args.params.get('outputList') or []
    texts = args.params.get('texts') or []
    label = str(args.params.get('label') or '配音').strip()
    links = []
    errors = []
    for index, row in enumerate(rows):
        data = row.get('data') if isinstance(row, dict) else None
        link = str(data.get('link') or '').strip() if isinstance(data, dict) else ''
        if link:
            links.append(link)
        else:
            errors.append(_message(row, index, label, texts))

    if not rows:
        raise RuntimeError('{}未返回任何批处理结果'.format(label))
    if errors:
        raise RuntimeError('语音合成失败；' + '；'.join(errors))
    return {'links': links, 'errors': []}
""".strip()

    code_meta = copy.deepcopy((normalizer.get("data") or {}).get("nodeMeta") or {})
    code_external = copy.deepcopy(
        ((normalizer.get("_temp") or {}).get("externalData") or {})
    )
    for collector_id, (tts_id, label, text_output) in collector_sources.items():
        tts = nodes.get(tts_id)
        collector = nodes.get(collector_id)
        if tts is None or collector is None:
            raise ValueError(
                f"书单模板缺少配音链路节点 {tts_id}/{collector_id}"
            )

        tts_inputs = (tts.get("data") or {}).setdefault("inputs", {})
        tts_inputs.setdefault("batch", {})["concurrentSize"] = 1
        tts_inputs.setdefault("settingOnError", {})["retryTimes"] = 2

        collector["type"] = "5"
        collector_data = collector.setdefault("data", {})
        title = str(
            (collector_data.get("nodeMeta") or {}).get("title")
            or f"提取音频链接 {collector_id}"
        )
        collector_data["nodeMeta"] = copy.deepcopy(code_meta)
        collector_data["nodeMeta"]["title"] = title
        collector_data["nodeMeta"]["subTitle"] = "代码"
        collector_data["inputs"] = {
            "inputParameters": [
                {
                    "name": "outputList",
                    "input": {
                        "type": "list",
                        "schema": {"type": "object", "schema": []},
                        "value": {
                            "type": "ref",
                            "content": {
                                "source": "block-output",
                                "blockID": tts_id,
                                "name": "outputList",
                            },
                            "rawMeta": {"type": 103},
                        },
                    },
                },
                {
                    "name": "texts",
                    "input": {
                        "type": "list",
                        "schema": {"type": "string"},
                        "value": {
                            "type": "ref",
                            "content": {
                                "source": "block-output",
                                "blockID": "114310",
                                "name": text_output,
                            },
                            "rawMeta": {"type": 99},
                        },
                    },
                },
                {
                    "name": "label",
                    "input": {
                        "type": "string",
                        "value": {
                            "type": "literal",
                            "content": label,
                            "rawMeta": {"type": 1},
                        },
                    },
                },
            ],
            "code": collector_code,
            "language": 3,
            "settingOnError": {
                "switch": False,
                "processType": 1,
                "timeoutMs": 60_000,
                "retryTimes": 0,
            },
        }
        collector_data["outputs"] = [
            {
                "type": "list",
                "name": "links",
                "schema": {"type": "string"},
                "required": False,
            },
            {
                "type": "list",
                "name": "errors",
                "schema": {"type": "string"},
                "required": False,
            },
        ]
        collector_data["version"] = "v2"
        collector.setdefault("_temp", {})["externalData"] = copy.deepcopy(code_external)


def build_all() -> list[dict]:
    reports = []
    for profile in PROFILES:
        workflow = json.loads(profile["source"].read_text(encoding="utf-8"))
        if profile["run_prefix"] == "book_recorded_":
            ensure_book_batch_inputs(workflow)
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
