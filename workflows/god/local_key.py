#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从神工作流模板生成「本地草稿 key」变体。

把 19 个剪映小助手插件节点（create_draft / add_*）从模板中移除，替换为一个
「汇总草稿key」代码节点：按原调用顺序把各数据整形节点的输出组装成 key 数据包
（schema 见 docs/draft_key_schema.md），End 节点改为输出 key JSON 字符串。
拿到 key 后在本地执行 `python scripts/import_draft_key.py key.json` 生成草稿。

用法:
    python -m workflows.god.local_key                 # v7 母版 → 神工作流模板_本地草稿-v1.json
    python -m workflows.god.local_key 源模板.json 输出.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SOURCE = _REPO_ROOT / "神工作流模板_修改版-开场静态修正-v7.json"
DEFAULT_OUTPUT = _REPO_ROOT / "神工作流模板_本地草稿-v1.json"

AGGREGATE_NODE_ID = "300201"
KEYFRAME_CODE_NODE_ID = "201390"
END_NODE_ID = "900001"

_DRAFT_TOOLS = {"create_draft", "add_audios", "add_images", "add_captions", "add_keyframes", "add_effects"}

# 节点 id → key 里稳定可读的 call_id（换神变体节点 id 不变，可直接复用）
_CALL_IDS = {
    "178582": "bgm",
    "178583": "sfx",
    "117759": "voice",
    "192103": "main_images",
    "174538": "intro_images",
    "174537": "bg_images",
    "201377": "slide_b",
    "201378": "slide_c",
    "108685": "slide_a",
    "201391": "camera_kf",
    "150753": "focus_images",
    "195903": "title_lock",
    "126860": "top_label",
    "226902": "corner_tip",
    "121500": "main_captions",
    "177705": "opening_fx",
    "124207": "main_fx",
    "201368": "fg_images",
    "201371": "focus_close_up",
}

# add_keyframes 的运镜关键帧针对的调用（201390 的 image_segment_infos 来源 = 主体图层）
_KEYFRAME_TARGET_CALL = "main_images"

# 各工具的列表参数名
_LIST_PARAM = {
    "add_audios": "audio_infos",
    "add_images": "image_infos",
    "add_captions": "captions",
    "add_keyframes": "keyframes",
    "add_effects": "effect_infos",
}


def _api_name(node: dict) -> str | None:
    for param in ((node.get("data", {}).get("inputs", {}) or {}).get("apiParam") or []):
        if param.get("name") == "apiName":
            return param["input"]["value"]["content"]
    return None


def _input_params(node: dict) -> list[dict]:
    return (node.get("data", {}).get("inputs", {}) or {}).get("inputParameters") or []


def _topo_order(node_ids: set[str], edges: list[dict]) -> dict[str, int]:
    indegree = {nid: 0 for nid in node_ids}
    adjacency = defaultdict(list)
    for edge in edges:
        src, dst = edge.get("sourceNodeID"), edge.get("targetNodeID")
        if src in node_ids and dst in node_ids:
            adjacency[src].append(dst)
            indegree[dst] += 1
    queue = sorted(nid for nid, deg in indegree.items() if deg == 0)
    order: dict[str, int] = {}
    while queue:
        nid = queue.pop(0)
        order[nid] = len(order)
        for nxt in adjacency[nid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return order


def _collect_call_specs(nodes: dict[str, dict], edges: list[dict]) -> tuple[list[dict], dict]:
    """扫描剪映小助手节点，按拓扑序输出调用规格；返回 (call_specs, draft_cfg)。"""
    connected = {e.get("sourceNodeID") for e in edges} | {e.get("targetNodeID") for e in edges}
    order = _topo_order(set(nodes), edges)

    draft_cfg = {"width": 1920, "height": 1080}
    specs = []
    for node_id, node in nodes.items():
        tool = _api_name(node)
        if tool not in _DRAFT_TOOLS:
            continue
        if tool == "create_draft":
            for param in _input_params(node):
                value = param["input"].get("value", {})
                if value.get("type") == "literal" and param["name"] in ("width", "height"):
                    try:
                        draft_cfg[param["name"]] = int(float(value.get("content") or 0))
                    except (TypeError, ValueError):
                        pass
            continue
        if node_id not in connected:
            continue  # v7 里 201368/201371 无接线，不产生调用

        list_ref = None
        literals = {}
        for param in _input_params(node):
            name = param["name"]
            value = param["input"].get("value", {})
            if name == "draft_id":
                continue
            if value.get("type") == "ref":
                content = value.get("content", {})
                list_ref = (str(content.get("blockID")), str(content.get("name")))
            elif value.get("type") == "literal":
                literals[name] = value.get("content")
        if list_ref is None:
            continue
        specs.append(
            {
                "node_id": node_id,
                "call_id": _CALL_IDS.get(node_id, f"call_{node_id}"),
                "tool": tool,
                "ref": list_ref,
                "literals": literals,
                "order": order.get(node_id, 10**9),
            }
        )
    specs.sort(key=lambda spec: spec["order"])
    return specs, draft_cfg


_KEYFRAME_CODE = '''import json


def ensure_list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = []
    if not isinstance(value, list):
        value = []
    return value


def add_image_pan_keyframes(keyframes, items):
    pan_cycle = [
        {'sx': -0.2, 'sy': -0.07, 'ex': 0, 'ey': 0, 'ss': 1.7, 'es': 1.2},
        {'sx': 0.22, 'sy': 0.05, 'ex': 0, 'ey': 0, 'ss': 1.75, 'es': 1.22},
        {'sx': -0.06, 'sy': 0.09, 'ex': 0, 'ey': 0, 'ss': 1.65, 'es': 1.18},
        {'sx': 0.18, 'sy': -0.07, 'ex': 0, 'ey': 0, 'ss': 1.7, 'es': 1.2},
        {'sx': -0.22, 'sy': 0.05, 'ex': 0, 'ey': 0, 'ss': 1.75, 'es': 1.22},
        {'sx': 0.05, 'sy': -0.09, 'ex': 0, 'ey': 0, 'ss': 1.68, 'es': 1.19},
    ]
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        start = int(item.get('start') or 0)
        end = int(item.get('end') or start)
        if end <= start:
            continue
        motion = pan_cycle[idx % len(pan_cycle)]
        duration = end - start
        ref = {'call_id': '__KF_TARGET__', 'index': idx}
        for prop, sv, ev in (
            ('KFTypePositionX', motion['sx'], motion['ex']),
            ('KFTypePositionY', motion['sy'], motion['ey']),
            ('UNIFORM_SCALE', motion['ss'], motion['es']),
        ):
            keyframes.append({'offset': 0, 'property': prop, 'segment_ref': ref, 'value': sv})
            keyframes.append({'offset': duration, 'property': prop, 'segment_ref': ref, 'value': ev})


async def main(args: Args) -> Output:
    params = getattr(args, 'params', None) or {}
    image_infos = ensure_list(params.get('image_infos'))

    keyframes = []
    add_image_pan_keyframes(keyframes, image_infos)

    return {
        'keyframes': json.dumps(keyframes, ensure_ascii=False)
    }
'''


def _rewrite_keyframe_node(node: dict, imgs_ref: tuple[str, str]) -> None:
    """201390 原来消费 add_* 返回的真实 segment_id，改为从图片条目直接算 segment_ref。"""
    inputs = node["data"]["inputs"]
    inputs["inputParameters"] = [
        {
            "name": "image_infos",
            "input": {
                "type": "string",
                "value": {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": imgs_ref[0], "name": imgs_ref[1]},
                    "rawMeta": {"type": 1},
                },
            },
        }
    ]
    inputs["code"] = _KEYFRAME_CODE.replace("__KF_TARGET__", _KEYFRAME_TARGET_CALL)
    node["data"]["outputs"] = [{"type": "string", "name": "keyframes", "required": False}]


def _build_aggregate_code(specs: list[dict], draft_cfg: dict) -> str:
    """生成汇总代码节点源码：输入名 in_<call_id>，输出 draft_key 字符串。"""
    lines = [
        "import json",
        "import time",
        "",
        "",
        "def ensure_list(value):",
        "    if isinstance(value, str):",
        "        try:",
        "            value = json.loads(value)",
        "        except Exception:",
        "            value = []",
        "    if not isinstance(value, list):",
        "        value = []",
        "    return value",
        "",
        "",
        "async def main(args: Args) -> Output:",
        "    params = getattr(args, 'params', None) or {}",
        "    calls = []",
    ]
    for spec in specs:
        call_id = spec["call_id"]
        tool = spec["tool"]
        list_param = _LIST_PARAM[tool]
        literals = {k: v for k, v in spec["literals"].items() if v not in (None, "")}
        lines.append(f"    items = ensure_list(params.get('in_{call_id}'))")
        lines.append("    if items:")
        params_literal = json.dumps(literals, ensure_ascii=False) if literals else "{}"
        lines.append(f"        call_params = {params_literal}")
        lines.append(f"        call_params['{list_param}'] = items")
        lines.append(f"        calls.append({{'call_id': '{call_id}', 'tool': '{tool}', 'params': call_params}})")
    lines.extend(
        [
            "    key = {",
            "        'schema_version': '1.0',",
            "        'kind': 'jianying_draft_key',",
            "        'meta': {'workflow': '神工作流模板_本地草稿', 'run_id': 'god_local_' + str(int(time.time()))},",
            f"        'draft': {{'width': {draft_cfg['width']}, 'height': {draft_cfg['height']}, 'name': '神话解说_本地草稿'}},",
            "        'calls': calls,",
            "    }",
            "    return {'draft_key': json.dumps(key, ensure_ascii=False)}",
        ]
    )
    return "\n".join(lines)


def _build_aggregate_node(specs: list[dict], draft_cfg: dict) -> dict:
    input_parameters = []
    for spec in specs:
        block_id, name = spec["ref"]
        input_parameters.append(
            {
                "name": f"in_{spec['call_id']}",
                "input": {
                    "type": "string",
                    "value": {
                        "type": "ref",
                        "content": {"source": "block-output", "blockID": block_id, "name": name},
                        "rawMeta": {"type": 1},
                    },
                },
            }
        )
    return {
        "id": AGGREGATE_NODE_ID,
        "type": "5",
        "meta": {"position": {"x": 5200.0, "y": -400.0}},
        "data": {
            "nodeMeta": {
                "description": "把整条草稿装配序列汇总成 key 数据包，本地 import_draft_key 消费",
                "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Code-v2.jpg",
                "title": "汇总草稿key",
            },
            "inputs": {
                "inputParameters": input_parameters,
                "code": _build_aggregate_code(specs, draft_cfg),
                "language": 3,
                "settingOnError": {"switch": False, "processType": 1, "timeoutMs": 60000, "retryTimes": 0},
            },
            "outputs": [{"type": "string", "name": "draft_key", "required": False}],
            "version": "v2",
        },
    }


def _remove_nodes_with_stitch(template: dict, remove_ids: set[str]) -> None:
    """删除节点并把它的前驱直连后继，保持链式执行顺序。"""
    edges = template["json"]["edges"]
    for node_id in remove_ids:
        incoming = [e for e in edges if e.get("targetNodeID") == node_id]
        outgoing = [e for e in edges if e.get("sourceNodeID") == node_id]
        edges = [e for e in edges if e.get("sourceNodeID") != node_id and e.get("targetNodeID") != node_id]
        for in_edge in incoming:
            for out_edge in outgoing:
                if in_edge.get("sourceNodeID") != out_edge.get("targetNodeID"):
                    edges.append({"sourceNodeID": in_edge["sourceNodeID"], "targetNodeID": out_edge["targetNodeID"]})
    template["json"]["edges"] = edges
    template["json"]["nodes"] = [n for n in template["json"]["nodes"] if n["id"] not in remove_ids]


def generate_local_key_workflow(source_path: Path | str = DEFAULT_SOURCE, output_path: Path | str = DEFAULT_OUTPUT) -> dict:
    source_path = Path(source_path)
    output_path = Path(output_path)
    template = json.loads(source_path.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in template["json"]["nodes"]}
    edges = template["json"]["edges"]

    specs, draft_cfg = _collect_call_specs(nodes, edges)
    if not specs:
        raise ValueError("模板里没有找到剪映小助手调用节点")

    # add_keyframes 调用改为消费 201390 重写后的输出
    keyframe_ref_source = None
    for spec in specs:
        if spec["tool"] == "add_keyframes":
            keyframe_ref_source = spec["ref"]
            spec["ref"] = (KEYFRAME_CODE_NODE_ID, "keyframes")

    main_images_spec = next((s for s in specs if s["call_id"] == _KEYFRAME_TARGET_CALL), None)
    if keyframe_ref_source is not None:
        if main_images_spec is None:
            raise ValueError(f"找不到运镜关键帧的目标调用 {_KEYFRAME_TARGET_CALL}")
        _rewrite_keyframe_node(nodes[KEYFRAME_CODE_NODE_ID], main_images_spec["ref"])

    # 移除全部插件节点（含 create_draft 与未接线的 201368/201371）
    plugin_ids = {n["id"] for n in template["json"]["nodes"] if _api_name(n) in _DRAFT_TOOLS}
    _remove_nodes_with_stitch(template, plugin_ids)

    # 汇总节点插到 End 之前
    aggregate = _build_aggregate_node(specs, draft_cfg)
    template["json"]["nodes"].append(aggregate)
    edges = template["json"]["edges"]
    end_predecessors = [e for e in edges if e.get("targetNodeID") == END_NODE_ID]
    edges = [e for e in edges if e.get("targetNodeID") != END_NODE_ID]
    for edge in end_predecessors:
        edges.append({"sourceNodeID": edge["sourceNodeID"], "targetNodeID": AGGREGATE_NODE_ID})
    edges.append({"sourceNodeID": AGGREGATE_NODE_ID, "targetNodeID": END_NODE_ID})
    template["json"]["edges"] = edges

    # End 节点输出 key 字符串
    end_node = next(n for n in template["json"]["nodes"] if n["id"] == END_NODE_ID)
    end_node["data"]["inputs"]["inputParameters"] = [
        {
            "name": "draft_key",
            "input": {
                "type": "string",
                "value": {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": AGGREGATE_NODE_ID, "name": "draft_key"},
                    "rawMeta": {"type": 1},
                },
            },
        }
    ]

    from workflows.god.topology_fix import fix_coze_edge_topology

    fix_coze_edge_topology(template)

    output_path.write_text(json.dumps(template, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "output": str(output_path),
        "calls": [{"call_id": s["call_id"], "tool": s["tool"], "ref": f"{s['ref'][0]}.{s['ref'][1]}"} for s in specs],
        "draft": draft_cfg,
        "removed_nodes": sorted(plugin_ids),
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    dst = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT
    report = generate_local_key_workflow(src, dst)
    print(json.dumps(report, ensure_ascii=False, indent=2))
