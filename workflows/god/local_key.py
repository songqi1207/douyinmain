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


def _rewrite_keyframe_node(node: dict, imgs_ref: tuple[str, str], target_call_id: str) -> None:
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
    inputs.pop("apiParam", None)
    inputs["code"] = _KEYFRAME_CODE.replace("__KF_TARGET__", target_call_id)
    inputs["language"] = 3
    node["type"] = "5"
    node["data"]["outputs"] = [{"type": "string", "name": "keyframes", "required": False}]


def _literal_params(node: dict) -> dict:
    literals = {}
    for param in _input_params(node):
        value = (param.get("input") or {}).get("value") or {}
        if value.get("type") == "literal":
            literals[str(param.get("name") or "")] = value.get("content")
    return literals


def _build_curve_keyframe_code(node: dict, target_call_id: str) -> str:
    literals = _literal_params(node)
    property_type = str(literals.get("ctype") or "KFTypePositionX")
    offsets = [float(item) for item in str(literals.get("offsets") or "0|100").split("|") if item != ""]
    values = [float(item) for item in str(literals.get("values") or "0|0").split("|") if item != ""]
    if len(offsets) != len(values) or not offsets:
        raise ValueError(f"关键帧节点 {node.get('id')} 的 offsets/values 数量不一致")

    dimension_name = "width" if property_type in {"KFTypePositionX", "KFTypeScaleX"} else "height"
    try:
        dimension = float(literals.get(dimension_name) or 0)
    except (TypeError, ValueError):
        dimension = 0
    if dimension > 0 and any(abs(value) > 3 for value in values):
        values = [round(value / dimension, 8) for value in values]

    return "\n".join(
        [
            "import json",
            "",
            "",
            "def ensure_list(value):",
            "    if isinstance(value, str):",
            "        try:",
            "            value = json.loads(value)",
            "        except Exception:",
            "            value = []",
            "    return value if isinstance(value, list) else []",
            "",
            "",
            "async def main(args: Args) -> Output:",
            "    params = getattr(args, 'params', None) or {}",
            "    image_infos = ensure_list(params.get('image_infos'))",
            f"    offsets = {offsets!r}",
            f"    values = {values!r}",
            "    keyframes = []",
            "    for index, item in enumerate(image_infos):",
            "        if not isinstance(item, dict):",
            "            continue",
            "        start = int(item.get('start') or 0)",
            "        end = int(item.get('end') or start)",
            "        duration = max(end - start, 0)",
            "        if duration <= 0:",
            "            continue",
            f"        segment_ref = {{'call_id': {target_call_id!r}, 'index': index}}",
            "        for percent, value in zip(offsets, values):",
            "            keyframes.append({",
            "                'offset': int(round(duration * percent / 100.0)),",
            f"                'property': {property_type!r},",
            "                'segment_ref': segment_ref,",
            "                'value': value,",
            "            })",
            "    return {'keyframes': json.dumps(keyframes, ensure_ascii=False)}",
        ]
    )


def _rewrite_curve_keyframe_node(
    node: dict,
    imgs_ref: tuple[str, str],
    target_call_id: str,
) -> None:
    code = _build_curve_keyframe_code(node, target_call_id)
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
    inputs.pop("apiParam", None)
    inputs["code"] = code
    inputs["language"] = 3
    node["type"] = "5"
    node["data"]["outputs"] = [{"type": "string", "name": "keyframes", "required": False}]


def _batch_inputs(node: dict) -> dict[str, dict]:
    batch = ((node.get("data") or {}).get("inputs") or {}).get("batch") or {}
    result = {}
    for item in batch.get("inputLists") or []:
        value = (item.get("input") or {}).get("value") or {}
        content = value.get("content") or {}
        if value.get("type") == "ref" and isinstance(content, dict):
            result[str(item.get("name") or "")] = content
    return result


def _rewrite_batch_image_spec(node: dict, spec: dict) -> None:
    batch_refs = _batch_inputs(node)
    if not batch_refs:
        return

    source_name = None
    dynamic_fields = {}
    literals = {}
    for param in _input_params(node):
        name = str(param.get("name") or "")
        if name == "draft_id":
            continue
        value = (param.get("input") or {}).get("value") or {}
        content = value.get("content") or {}
        if value.get("type") == "literal":
            literals[name] = value.get("content")
        elif value.get("type") == "ref" and isinstance(content, dict) and str(content.get("blockID")) == str(node.get("id")):
            batch_name = str(content.get("name") or "").split(".", 1)[0]
            if name == "image_infos":
                source_name = batch_name
            else:
                dynamic_fields[name] = batch_name
    if not source_name or source_name not in batch_refs:
        raise ValueError(f"批量图片节点 {node.get('id')} 没有找到 image_infos 输入列表")

    input_parameters = []
    for name, content in batch_refs.items():
        input_parameters.append(
            {
                "name": f"batch_{name}",
                "input": {
                    "type": "list",
                    "value": {
                        "type": "ref",
                        "content": {
                            "source": "block-output",
                            "blockID": str(content.get("blockID")),
                            "name": str(content.get("name")),
                        },
                        "rawMeta": {"type": 99},
                    },
                },
            }
        )

    lines = [
        "import json",
        "",
        "",
        "def ensure_list(value):",
        "    if isinstance(value, str):",
        "        try:",
        "            value = json.loads(value)",
        "        except Exception:",
        "            value = []",
        "    return value if isinstance(value, list) else []",
        "",
        "",
        "async def main(args: Args) -> Output:",
        "    params = getattr(args, 'params', None) or {}",
        f"    source_rows = ensure_list(params.get('batch_{source_name}'))",
        f"    literals = {literals!r}",
        f"    dynamic_fields = {dynamic_fields!r}",
        "    dynamic_values = {name: ensure_list(params.get('batch_' + batch_name)) for name, batch_name in dynamic_fields.items()}",
        "    image_infos = []",
        "    for index, row in enumerate(source_rows):",
        "        items = ensure_list(row)",
        "        if not items and isinstance(row, dict):",
        "            items = [row]",
        "        for item in items:",
        "            if not isinstance(item, dict):",
        "                continue",
        "            copied = dict(item)",
        "            copied.update(literals)",
        "            for field, values in dynamic_values.items():",
        "                if index < len(values):",
        "                    copied[field] = values[index]",
        "            image_infos.append(copied)",
        "    return {'image_infos': json.dumps(image_infos, ensure_ascii=False)}",
    ]

    inputs = node["data"]["inputs"]
    inputs["inputParameters"] = input_parameters
    inputs.pop("batch", None)
    inputs.pop("apiParam", None)
    inputs["code"] = "\n".join(lines)
    inputs["language"] = 3
    node["type"] = "5"
    node["data"]["outputs"] = [{"type": "string", "name": "image_infos", "required": False}]
    spec["ref"] = (str(node["id"]), "image_infos")


def _rewrite_batch_image_specs(nodes: dict[str, dict], specs: list[dict]) -> None:
    for spec in specs:
        if spec["tool"] != "add_images":
            continue
        node = nodes[spec["node_id"]]
        batch = ((node.get("data") or {}).get("inputs") or {}).get("batch") or {}
        if batch.get("batchEnable"):
            _rewrite_batch_image_spec(node, spec)


def _rewrite_batch_curve_keyframe_node(node: dict, target_spec: dict) -> None:
    literals = _literal_params(node)
    property_type = str(literals.get("ctype") or "KFTypePositionX")
    dimension_name = "width" if property_type in {"KFTypePositionX", "KFTypeScaleX"} else "height"
    try:
        dimension = float(literals.get(dimension_name) or 0)
    except (TypeError, ValueError):
        dimension = 0

    batch_refs = _batch_inputs(node)
    values_batch_name = None
    offsets_ref = None
    for param in _input_params(node):
        name = str(param.get("name") or "")
        value = (param.get("input") or {}).get("value") or {}
        content = value.get("content") or {}
        if value.get("type") != "ref" or not isinstance(content, dict):
            continue
        if str(content.get("blockID")) == str(node.get("id")) and name == "values":
            values_batch_name = str(content.get("name") or "").split(".", 1)[0]
        elif name == "offsets":
            offsets_ref = content
    if not values_batch_name or values_batch_name not in batch_refs or offsets_ref is None:
        raise ValueError(f"批量关键帧节点 {node.get('id')} 缺少 values/offsets 输入")

    values_ref = batch_refs[values_batch_name]
    inputs = node["data"]["inputs"]
    inputs["inputParameters"] = [
        {
            "name": "image_infos",
            "input": {
                "type": "string",
                "value": {
                    "type": "ref",
                    "content": {
                        "source": "block-output",
                        "blockID": target_spec["ref"][0],
                        "name": target_spec["ref"][1],
                    },
                    "rawMeta": {"type": 1},
                },
            },
        },
        {
            "name": "value_rows",
            "input": {
                "type": "list",
                "value": {
                    "type": "ref",
                    "content": {
                        "source": "block-output",
                        "blockID": str(values_ref.get("blockID")),
                        "name": str(values_ref.get("name")),
                    },
                    "rawMeta": {"type": 99},
                },
            },
        },
        {
            "name": "offset_rows",
            "input": {
                "type": "string",
                "value": {
                    "type": "ref",
                    "content": {
                        "source": "block-output",
                        "blockID": str(offsets_ref.get("blockID")),
                        "name": str(offsets_ref.get("name")),
                    },
                    "rawMeta": {"type": 1},
                },
            },
        },
    ]
    inputs.pop("batch", None)
    inputs.pop("apiParam", None)
    inputs["code"] = "\n".join(
        [
            "import json",
            "",
            "",
            "def ensure_list(value):",
            "    if isinstance(value, str):",
            "        try:",
            "            parsed = json.loads(value)",
            "            if isinstance(parsed, list):",
            "                return parsed",
            "        except Exception:",
            "            pass",
            "    return value if isinstance(value, list) else []",
            "",
            "",
            "def series(value, index):",
            "    rows = ensure_list(value)",
            "    if rows:",
            "        value = rows[index] if index < len(rows) else rows[-1]",
            "    if isinstance(value, dict):",
            "        value = value.get('output') or value.get('value') or ''",
            "    if isinstance(value, list):",
            "        return [float(item) for item in value]",
            "    return [float(item) for item in str(value or '').replace('。', '|').split('|') if str(item).strip()]",
            "",
            "",
            "async def main(args: Args) -> Output:",
            "    params = getattr(args, 'params', None) or {}",
            "    image_infos = ensure_list(params.get('image_infos'))",
            "    keyframes = []",
            "    for index, item in enumerate(image_infos):",
            "        if not isinstance(item, dict):",
            "            continue",
            "        start = int(item.get('start') or 0)",
            "        end = int(item.get('end') or start)",
            "        duration = max(end - start, 0)",
            "        offsets = series(params.get('offset_rows'), index)",
            "        values = series(params.get('value_rows'), index)",
            f"        if {dimension!r} > 0 and any(abs(value) > 3 for value in values):",
            f"            values = [value / {dimension!r} for value in values]",
            "        if duration <= 0 or len(offsets) != len(values):",
            "            continue",
            f"        segment_ref = {{'call_id': {target_spec['call_id']!r}, 'index': index}}",
            "        for percent, value in zip(offsets, values):",
            "            keyframes.append({",
            "                'offset': int(round(duration * percent / 100.0)),",
            f"                'property': {property_type!r},",
            "                'segment_ref': segment_ref,",
            "                'value': value,",
            "            })",
            "    return {'keyframes': json.dumps(keyframes, ensure_ascii=False)}",
        ]
    )
    inputs["language"] = 3
    node["type"] = "5"
    node["data"]["outputs"] = [{"type": "string", "name": "keyframes", "required": False}]


def _rewrite_keyframe_specs(nodes: dict[str, dict], specs: list[dict]) -> None:
    specs_by_node = {spec["node_id"]: spec for spec in specs}
    for spec in specs:
        if spec["tool"] != "add_keyframes":
            continue
        source_id = spec["ref"][0]
        source_node = nodes.get(source_id)
        if source_node is None:
            raise ValueError(f"关键帧数据节点不存在: {source_id}")

        source_batch = ((source_node.get("data") or {}).get("inputs") or {}).get("batch") or {}
        if _api_name(source_node) == "add_keyframes" and source_batch.get("batchEnable"):
            generator_node = None
            for content in _batch_inputs(source_node).values():
                candidate = nodes.get(str(content.get("blockID") or ""))
                if candidate is not None and _api_name(candidate) == "keyframes_infos":
                    generator_node = candidate
                    break
            if generator_node is None:
                raise ValueError(f"批量关键帧节点 {source_id} 没有找到数据生成节点")
            target_spec = None
            for content in _batch_inputs(generator_node).values():
                candidate = specs_by_node.get(str(content.get("blockID") or ""))
                if candidate and candidate["tool"] == "add_images":
                    target_spec = candidate
                    break
            if target_spec is None:
                raise ValueError(f"批量关键帧节点 {source_id} 没有找到对应的图片轨道")
            _rewrite_batch_curve_keyframe_node(generator_node, target_spec)
            spec["ref"] = (str(generator_node["id"]), "keyframes")
            continue

        target_spec = None
        for param in _input_params(source_node):
            value = (param.get("input") or {}).get("value") or {}
            content = value.get("content") or {}
            if value.get("type") != "ref" or not isinstance(content, dict):
                continue
            candidate = specs_by_node.get(str(content.get("blockID") or ""))
            if candidate and candidate["tool"] == "add_images":
                target_spec = candidate
                break
        if target_spec is None:
            raise ValueError(f"关键帧节点 {source_id} 没有找到对应的图片轨道")

        if _api_name(source_node) == "keyframes_infos":
            _rewrite_curve_keyframe_node(source_node, target_spec["ref"], target_spec["call_id"])
        else:
            _rewrite_keyframe_node(source_node, target_spec["ref"], target_spec["call_id"])
        spec["ref"] = (source_id, "keyframes")


def _build_aggregate_code(
    specs: list[dict],
    draft_cfg: dict,
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> str:
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
            f"        'meta': {{'workflow': {workflow_name!r}, 'run_id': {run_prefix!r} + str(int(time.time() * 1000))}},",
            f"        'draft': {{'width': {draft_cfg['width']}, 'height': {draft_cfg['height']}, 'name': {draft_name!r}}},",
            "        'calls': calls,",
            "    }",
            "    return {'draft_key': json.dumps(key, ensure_ascii=False)}",
        ]
    )
    return "\n".join(lines)


def _build_aggregate_node(
    specs: list[dict],
    draft_cfg: dict,
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> dict:
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
                "code": _build_aggregate_code(
                    specs,
                    draft_cfg,
                    workflow_name=workflow_name,
                    draft_name=draft_name,
                    run_prefix=run_prefix,
                ),
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


def convert_workflow_to_local_key(
    template: dict,
    *,
    workflow_name: str = "神工作流模板_本地草稿",
    draft_name: str = "神话解说_本地草稿",
    run_prefix: str = "god_local_",
) -> dict:
    nodes = {n["id"]: n for n in template["json"]["nodes"]}
    edges = template["json"]["edges"]

    specs, draft_cfg = _collect_call_specs(nodes, edges)
    if not specs:
        raise ValueError("模板里没有找到剪映小助手调用节点")

    # 批量 add_images 先改成代码节点，把循环输入合并为一条可移植图片调用。
    _rewrite_batch_image_specs(nodes, specs)

    # 关键帧原来依赖 add_images 返回的 segment_id。改成依赖原始图片列表，并在 key 中
    # 使用 {call_id,index}，本地导入时再解析成真实 segment_id。
    _rewrite_keyframe_specs(nodes, specs)

    # 移除全部插件节点（含 create_draft 与未接线的 201368/201371）
    plugin_ids = {n["id"] for n in template["json"]["nodes"] if _api_name(n) in _DRAFT_TOOLS}
    _remove_nodes_with_stitch(template, plugin_ids)

    # 汇总节点插到 End 之前
    aggregate = _build_aggregate_node(
        specs,
        draft_cfg,
        workflow_name=workflow_name,
        draft_name=draft_name,
        run_prefix=run_prefix,
    )
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
    return {
        "calls": [{"call_id": s["call_id"], "tool": s["tool"], "ref": f"{s['ref'][0]}.{s['ref'][1]}"} for s in specs],
        "draft": draft_cfg,
        "removed_nodes": sorted(plugin_ids),
    }


def generate_local_key_workflow(
    source_path: Path | str = DEFAULT_SOURCE,
    output_path: Path | str = DEFAULT_OUTPUT,
    *,
    workflow_name: str = "神工作流模板_本地草稿",
    draft_name: str = "神话解说_本地草稿",
    run_prefix: str = "god_local_",
) -> dict:
    source_path = Path(source_path)
    output_path = Path(output_path)
    template = json.loads(source_path.read_text(encoding="utf-8"))
    report = convert_workflow_to_local_key(
        template,
        workflow_name=workflow_name,
        draft_name=draft_name,
        run_prefix=run_prefix,
    )
    output_path.write_text(json.dumps(template, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"output": str(output_path), **report}


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    dst = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT
    report = generate_local_key_workflow(src, dst)
    print(json.dumps(report, ensure_ascii=False, indent=2))
