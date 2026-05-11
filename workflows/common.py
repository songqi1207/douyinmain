#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""所有工作流类型共享的辅助函数。"""

from config import MIHE_PROMPT_MAX_CHARS, MIHE_PROMPT_CLAMP_NODE_ID


def make_ref(block_id, name, raw_type=1):
    """构造 Coze 工作流 block-output 引用值。"""
    return {
        "type": "ref",
        "content": {"source": "block-output", "blockID": block_id, "name": name},
        "rawMeta": {"type": raw_type},
    }


def upsert_output(outputs, name, value, description=None, required=True):
    for output in outputs:
        if output.get('name') == name:
            output['type'] = 'string'
            output['required'] = required
            if description is not None:
                output['description'] = description
            output['value'] = value
            output['defaultValue'] = value
            return

    outputs.append({
        "type": "string",
        "name": name,
        "required": required,
        "description": description or "",
        "defaultValue": value,
        "value": value
    })


def _mihe_prompt_clamp_source_code():
    _mihe_cap = MIHE_PROMPT_MAX_CHARS
    return f"""async def main(args: Args) -> Output:
    _p = getattr(args, "params", None) or {{}}
    raw = str(_p.get("prompt_in") or "").strip()
    max_len = {_mihe_cap}
    if len(raw) <= max_len:
        out = raw
    else:
        cut = raw[:max_len]
        out = cut
        for sep in ("。", "，", ",", ";", "；", "\\n", "、"):
            i = cut.rfind(sep)
            if i > int(max_len * 0.55):
                out = cut[: i + 1].strip()
                break
    if len(out) > max_len:
        out = out[:max_len].strip()
    return {{"prompt_out": out}}"""


def ensure_mihe_prompt_clamp(template, nodes, llm_node_id="120003", image_node_id="117364"):
    """
    在绘画 LLM 与即梦生图之间插入代码截断，避免超过米核约 800 字上限。
    """
    mihe_clamp_id = MIHE_PROMPT_CLAMP_NODE_ID
    mihe_clamp_code = _mihe_prompt_clamp_source_code()
    if mihe_clamp_id not in nodes:
        nodes[mihe_clamp_id] = {
            "id": mihe_clamp_id,
            "type": "5",
            "meta": {"position": {"x": -2809.0, "y": -922.0}},
            "data": {
                "nodeMeta": {
                    "description": "\u7c73\u6838\u5373\u68a6\u63d0\u793a\u8bcd\u622a\u65ad\u81f3\u5b89\u5168\u957f\u5ea6\uff08\u63a5\u53e3\u9650\u5236\uff09",
                    "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Code-v2.jpg",
                    "title": "\u7c73\u6838\u63d0\u793a\u8bcd\u622a\u65ad",
                },
                "inputs": {
                    "inputParameters": [
                        {
                            "name": "prompt_in",
                            "input": {
                                "type": "string",
                                "value": {
                                    "type": "ref",
                                    "content": {
                                        "source": "block-output",
                                        "blockID": llm_node_id,
                                        "name": "prompt",
                                    },
                                    "rawMeta": {"type": 1},
                                },
                            },
                        }
                    ],
                    "code": mihe_clamp_code,
                    "language": 3,
                    "settingOnError": {"switch": False, "processType": 1, "timeoutMs": 60000, "retryTimes": 0},
                },
                "outputs": [{"type": "string", "name": "prompt_out", "required": False}],
                "version": "v2",
            },
        }
        template["json"]["nodes"].append(nodes[mihe_clamp_id])
    else:
        ins = nodes[mihe_clamp_id].setdefault("data", {}).setdefault("inputs", {})
        ins["code"] = mihe_clamp_code
        for param in (ins.get("inputParameters") or []):
            if param.get("name") == "prompt_in":
                param["input"]["value"] = {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": llm_node_id, "name": "prompt"},
                    "rawMeta": {"type": 1},
                }
                break

    edges_main = template["json"]["edges"]
    edges_main = [
        e
        for e in edges_main
        if not (
            (e.get("sourceNodeID") == llm_node_id and e.get("targetNodeID") == image_node_id)
            or (e.get("sourceNodeID") == llm_node_id and e.get("targetNodeID") == mihe_clamp_id)
            or (e.get("sourceNodeID") == mihe_clamp_id and e.get("targetNodeID") == image_node_id)
        )
    ]
    edges_main.extend(
        [
            {"sourceNodeID": llm_node_id, "targetNodeID": mihe_clamp_id},
            {"sourceNodeID": mihe_clamp_id, "targetNodeID": image_node_id},
        ]
    )
    template["json"]["edges"] = edges_main

    if image_node_id in nodes:
        for _p in (nodes[image_node_id].get("data", {}).get("inputs", {}).get("inputParameters") or []):
            if _p.get("name") == "prompt":
                _p["input"]["value"] = {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": mihe_clamp_id, "name": "prompt_out"},
                    "rawMeta": {"type": 1},
                }
                break
