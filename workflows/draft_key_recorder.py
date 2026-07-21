#!/usr/bin/env python3
"""Append exactly one ``draft_key`` recorder to an intact Mihe workflow.

The workflow templates and all Mihe plugin nodes are left untouched.  The only
graph change is to insert one code node immediately before End.  That node
records the resolved inputs sent to Mihe and uses plugin ``segment_infos``
outputs to replace server-only segment ids with portable ``segment_ref`` values.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from workflows.god.local_key import (
    END_NODE_ID,
    _LIST_PARAM,
    _collect_call_specs,
)


RECORDER_NODE_ID = "390001"
_NODE_SPACING = 420.0


def _unique_numeric_id(nodes: dict[str, dict[str, Any]], preferred: int) -> str:
    candidate = preferred
    while str(candidate) in nodes:
        candidate += 1
    return str(candidate)


def _input_params(node: dict[str, Any]) -> list[dict[str, Any]]:
    return ((node.get("data") or {}).get("inputs") or {}).get("inputParameters") or []


def _batch_inputs(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    batch = ((node.get("data") or {}).get("inputs") or {}).get("batch") or {}
    result: dict[str, dict[str, Any]] = {}
    for item in batch.get("inputLists") or []:
        value = ((item.get("input") or {}).get("value") or {})
        content = value.get("content") or {}
        if value.get("type") == "ref" and isinstance(content, dict):
            result[str(item.get("name") or "")] = content
    return result


def _batch_descriptor(node: dict[str, Any], list_param: str) -> dict[str, Any] | None:
    inputs = (node.get("data") or {}).get("inputs") or {}
    batch = inputs.get("batch") or {}
    if not batch.get("batchEnable"):
        return None

    refs = _batch_inputs(node)
    source_name = ""
    source_path = ""
    dynamic_fields: dict[str, dict[str, str]] = {}
    for param in _input_params(node):
        name = str(param.get("name") or "")
        if name == "draft_id":
            continue
        value = ((param.get("input") or {}).get("value") or {})
        content = value.get("content") or {}
        if value.get("type") != "ref" or not isinstance(content, dict):
            continue
        if str(content.get("blockID") or "") != str(node.get("id")):
            continue
        batch_ref = str(content.get("name") or "")
        batch_name, _, nested_path = batch_ref.partition(".")
        if name == list_param:
            source_name = batch_name
            source_path = nested_path
        else:
            dynamic_fields[name] = {"batch": batch_name, "path": nested_path}

    if not source_name or source_name not in refs:
        raise ValueError(f"批处理节点 {node.get('id')} 缺少 {list_param} 的输入列表")
    return {
        "refs": refs,
        "source_name": source_name,
        "source_path": source_path,
        "dynamic_fields": dynamic_fields,
    }


def _output_definition(
    nodes: dict[str, dict[str, Any]], content: dict[str, Any]
) -> dict[str, Any] | None:
    node = nodes.get(str(content.get("blockID")))
    if node is None:
        return None
    output_name = str(content.get("name"))
    return next(
        (
            output
            for output in ((node.get("data") or {}).get("outputs") or [])
            if str(output.get("name")) == output_name
        ),
        None,
    )


def _ref_parameter(
    name: str,
    content: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    *,
    input_type: str = "string",
) -> dict[str, Any]:
    input_definition: dict[str, Any] = {"type": input_type}
    raw_meta_type = {
        "string": 1,
        "integer": 2,
        "boolean": 3,
        "float": 4,
        "number": 4,
    }.get(input_type, 1)
    if input_type == "list":
        source_output = _output_definition(nodes, content) or {}
        schema = copy.deepcopy(source_output.get("schema"))
        if not isinstance(schema, dict):
            # Mihe segment_infos is a list of objects, but its output declaration
            # omits the schema.  Coze code-node inputs require it explicitly.
            schema = {"type": "object", "schema": []}
        input_definition["schema"] = schema
        raw_meta_type = 99 if schema.get("type") == "string" else 103

    input_definition["value"] = {
        "type": "ref",
        "content": {
            "source": "block-output",
            "blockID": str(content.get("blockID")),
            "name": str(content.get("name")),
        },
        "rawMeta": {"type": raw_meta_type},
    }
    return {
        "name": name,
        "input": input_definition,
    }


def _recorder_specs(workflow: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
    call_specs, draft_cfg = _collect_call_specs(nodes, workflow["json"]["edges"])
    recorder_specs: list[dict[str, Any]] = []
    for spec in call_specs:
        node = nodes[spec["node_id"]]
        list_param = _LIST_PARAM[spec["tool"]]
        batch = _batch_descriptor(node, list_param)
        segment_output_name = None
        for output in ((node.get("data") or {}).get("outputs") or []):
            if output.get("name") == "segment_infos":
                segment_output_name = "segment_infos"
                break
            schema = output.get("schema") or {}
            nested_names = {
                str(item.get("name") or "")
                for item in (schema.get("schema") or [])
                if isinstance(item, dict)
            }
            if "segment_infos" in nested_names:
                segment_output_name = str(output.get("name") or "")
                break
        recorder_specs.append(
            {
                **spec,
                "source_node_title": str(
                    ((node.get("data") or {}).get("nodeMeta") or {}).get("title") or ""
                ),
                "list_param": list_param,
                "batch": batch,
                "segment_output_name": segment_output_name,
            }
        )
    return recorder_specs, draft_cfg


def _recorder_inputs(
    specs: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    used_names: set[str] = set()

    def append(parameter: dict[str, Any]) -> None:
        name = str(parameter["name"])
        if name not in used_names:
            used_names.add(name)
            parameters.append(parameter)

    for spec in specs:
        call_id = spec["call_id"]
        batch = spec["batch"]
        if batch:
            for batch_name, content in batch["refs"].items():
                append(
                    _ref_parameter(
                        f"batch_{call_id}_{batch_name}",
                        content,
                        nodes,
                        input_type="list",
                    )
                )
        else:
            append(
                _ref_parameter(
                    f"in_{call_id}",
                    {"blockID": spec["ref"][0], "name": spec["ref"][1]},
                    nodes,
                )
            )
            for field, ref in (spec.get("dynamic_refs") or {}).items():
                content = {"blockID": ref[0], "name": ref[1]}
                output = _output_definition(nodes, content) or {}
                input_type = str(output.get("type") or "string")
                append(
                    _ref_parameter(
                        f"arg_{call_id}_{field}",
                        content,
                        nodes,
                        input_type=input_type,
                    )
                )
        if spec["segment_output_name"]:
            append(
                _ref_parameter(
                    f"segments_{call_id}",
                    {"blockID": spec["node_id"], "name": spec["segment_output_name"]},
                    nodes,
                    input_type="list",
                )
            )
    return parameters


def _runtime_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runtime = []
    for spec in specs:
        batch = spec["batch"]
        batch_runtime = None
        if batch:
            batch_runtime = {
                "source_input": f"batch_{spec['call_id']}_{batch['source_name']}",
                "source_path": batch["source_path"],
                "dynamic_fields": {
                    field: {
                        "input": f"batch_{spec['call_id']}_{details['batch']}",
                        "path": details["path"],
                    }
                    for field, details in batch["dynamic_fields"].items()
                },
            }
        runtime.append(
            {
                "call_id": spec["call_id"],
                "tool": spec["tool"],
                "source_node_id": spec["node_id"],
                "source_node_title": spec["source_node_title"],
                "list_param": spec["list_param"],
                "input": None if batch else f"in_{spec['call_id']}",
                "batch": batch_runtime,
                "dynamic_inputs": {
                    field: f"arg_{spec['call_id']}_{field}"
                    for field in ((spec.get("dynamic_refs") or {}) if not batch else {})
                },
                "segments_input": f"segments_{spec['call_id']}" if spec["segment_output_name"] else None,
                "literals": spec["literals"],
            }
        )
    return runtime


def _recorder_code(
    specs: list[dict[str, Any]],
    draft_cfg: dict[str, int],
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> str:
    runtime_specs = _runtime_specs(specs)
    return f'''import json
import time


SPECS = {runtime_specs!r}


def decode(value):
    while isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            break
        if parsed == value:
            break
        value = parsed
    return value


def sequence(value):
    value = decode(value)
    if isinstance(value, list):
        return value
    if value in (None, ''):
        return []
    return [value]


def items(value):
    result = []
    for item in sequence(value):
        item = decode(item)
        if isinstance(item, list):
            result.extend(items(item))
        elif isinstance(item, dict):
            result.append(dict(item))
    return result


def at_path(value, path):
    value = decode(value)
    for part in str(path or '').split('.'):
        if not part:
            continue
        if not isinstance(value, dict):
            return None
        value = decode(value.get(part))
    return value


def batch_items(params, spec):
    batch = spec['batch']
    rows = sequence(params.get(batch['source_input']))
    dynamic_rows = {{
        field: sequence(params.get(details['input']))
        for field, details in batch['dynamic_fields'].items()
    }}
    result = []
    for index, row in enumerate(rows):
        source_value = at_path(row, batch['source_path'])
        for item in items(source_value):
            copied = dict(item)
            for field, details in batch['dynamic_fields'].items():
                values = dynamic_rows.get(field) or []
                if values:
                    raw = values[index] if index < len(values) else values[-1]
                    copied[field] = at_path(raw, details['path'])
            result.append(copied)
    return result


def segment_ids(value):
    found = []
    value = decode(value)
    if isinstance(value, dict):
        segment_id = value.get('id') or value.get('segment_id')
        if segment_id:
            found.append(str(segment_id))
        else:
            for child in value.values():
                found.extend(segment_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(segment_ids(child))
    return found


async def main(args: Args) -> Output:
    params = getattr(args, 'params', None) or {{}}
    calls = []
    segment_refs = {{}}
    unresolved_segment_ids = []
    skipped_empty_calls = []

    for spec in SPECS:
        call_items = batch_items(params, spec) if spec['batch'] else items(params.get(spec['input']))
        # Optional branches in the source workflow can legitimately produce an
        # empty list.  They are no-ops for Mihe and must not become invalid
        # draft_key calls (the local importer requires every call to have items).
        if not call_items:
            skipped_empty_calls.append({{
                'call_id': spec['call_id'],
                'tool': spec['tool'],
                'source_node_id': spec['source_node_id'],
                'source_node_title': spec['source_node_title'],
            }})
            continue
        if spec['tool'] == 'add_keyframes':
            normalized = []
            for item in call_items:
                copied = dict(item)
                segment_id = str(copied.get('segment_id') or '')
                if segment_id and segment_id in segment_refs:
                    copied.pop('segment_id', None)
                    copied['segment_ref'] = dict(segment_refs[segment_id])
                elif segment_id:
                    unresolved_segment_ids.append(segment_id)
                normalized.append(copied)
            call_items = normalized

        call_params = {{spec['list_param']: call_items}}
        call_params.update(spec['literals'])
        for field, input_name in spec['dynamic_inputs'].items():
            call_params[field] = decode(params.get(input_name))
        calls.append({{
            'call_id': spec['call_id'],
            'tool': spec['tool'],
            'source_node_id': spec['source_node_id'],
            'source_node_title': spec['source_node_title'],
            'params': call_params,
        }})

        if spec['segments_input']:
            for index, segment_id in enumerate(segment_ids(params.get(spec['segments_input']))):
                segment_refs[segment_id] = {{'call_id': spec['call_id'], 'index': index}}

    field_manifest = []
    for call in calls:
        item_fields = set()
        for value in call['params'].values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item_fields.update(item.keys())
        field_manifest.append({{
            'call_id': call['call_id'],
            'tool': call['tool'],
            'parameter_fields': sorted(call['params'].keys()),
            'item_fields': sorted(item_fields),
        }})

    key = {{
        'schema_version': '1.0',
        'kind': 'jianying_draft_key',
        'meta': {{
            'workflow': {workflow_name!r},
            'run_id': {run_prefix!r} + str(int(time.time() * 1000)),
            'source': 'mihe_plugin_call_record',
            'unresolved_segment_ids': unresolved_segment_ids,
            'template_operation_count': len(SPECS),
            'recorded_operation_count': len(calls),
            'skipped_empty_calls': skipped_empty_calls,
            'recorded_field_manifest': field_manifest,
        }},
        'draft': {{
            'width': {int(draft_cfg['width'])},
            'height': {int(draft_cfg['height'])},
            'name': {draft_name!r},
        }},
        'calls': calls,
    }}
    return {{'draft_key': json.dumps(key, ensure_ascii=False)}}
'''


def _recorder_node(
    recorder_id: str,
    specs: list[dict[str, Any]],
    draft_cfg: dict[str, int],
    nodes: dict[str, dict[str, Any]],
    prototype: dict[str, Any],
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> dict[str, Any]:
    # Start from a native code node so the clipboard JSON keeps Coze's required
    # nodeMeta/_temp/externalData fields.  Hand-building only id/type/data makes
    # Coze accept the JSON text but fail to render the graph and its edges.
    recorder = copy.deepcopy(prototype)
    recorder["id"] = recorder_id
    recorder["type"] = "5"
    recorder["meta"] = {"position": {"x": 0.0, "y": 0.0}}
    node_meta = recorder.setdefault("data", {}).setdefault("nodeMeta", {})
    node_meta.update(
        {
            "description": "记录米核插件调用，输出可携带的 draft_key JSON",
            "subTitle": "代码",
            "title": "记录 draftjsonkey（米核插件保持不变）",
        }
    )
    recorder["data"]["inputs"] = {
        "inputParameters": _recorder_inputs(specs, nodes),
        "code": _recorder_code(
            specs,
            draft_cfg,
            workflow_name=workflow_name,
            draft_name=draft_name,
            run_prefix=run_prefix,
        ),
        "language": 3,
        "settingOnError": {
            "switch": False,
            "processType": 1,
            "timeoutMs": 60000,
            "retryTimes": 0,
        },
    }
    recorder["data"]["outputs"] = [
        {"type": "string", "name": "draft_key", "required": False}
    ]
    recorder["data"]["version"] = "v2"
    temp = recorder.setdefault("_temp", {})
    temp["bounds"] = {"x": -180.0, "y": 0.0, "width": 360, "height": 112}
    return recorder


def _append_end_outputs(end_node: dict[str, Any], recorder_id: str) -> None:
    parameters = ((end_node.get("data") or {}).get("inputs") or {}).setdefault("inputParameters", [])
    legacy = next((item for item in parameters if item.get("name") == "output"), None)
    if legacy is None:
        raise ValueError("原工作流 End 节点没有 output/draft_id 输出")
    parameters[:] = [item for item in parameters if item.get("name") not in {"draft_id", "draft_key"}]
    draft_id = copy.deepcopy(legacy)
    draft_id["name"] = "draft_id"
    parameters.append(draft_id)
    parameters.append(
        {
            "name": "draft_key",
            "input": {
                "type": "string",
                "value": {
                    "type": "ref",
                    "content": {
                        "source": "block-output",
                        "blockID": recorder_id,
                        "name": "draft_key",
                    },
                    "rawMeta": {"type": 1},
                },
            },
        }
    )


def add_draft_key_recorder(
    workflow: dict[str, Any],
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> dict[str, Any]:
    """Insert one recorder before End without changing any Mihe plugin node."""

    nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
    if END_NODE_ID not in nodes:
        raise ValueError(f"工作流缺少 End 节点 {END_NODE_ID}")
    specs, draft_cfg = _recorder_specs(workflow)
    if not specs:
        raise ValueError("原工作流没有可记录的米核草稿调用")

    recorder_id = _unique_numeric_id(nodes, int(RECORDER_NODE_ID))
    prototype = next(
        (
            node
            for node in workflow["json"]["nodes"]
            if str(node.get("type")) == "5"
            and isinstance((node.get("data") or {}).get("nodeMeta"), dict)
            and isinstance(node.get("_temp"), dict)
        ),
        None,
    )
    if prototype is None:
        raise ValueError("原工作流没有可复用的原生代码节点结构")
    recorder = _recorder_node(
        recorder_id,
        specs,
        draft_cfg,
        nodes,
        prototype,
        workflow_name=workflow_name,
        draft_name=draft_name,
        run_prefix=run_prefix,
    )

    end_node = nodes[END_NODE_ID]
    end_position = end_node.setdefault("meta", {}).setdefault("position", {"x": 0.0, "y": 0.0})
    old_end_x = float(end_position.get("x") or 0.0)
    old_end_y = float(end_position.get("y") or 0.0)
    recorder["meta"]["position"] = {"x": old_end_x, "y": old_end_y}
    recorder["_temp"]["bounds"].update({"x": old_end_x - 180.0, "y": old_end_y})
    end_position["x"] = old_end_x + _NODE_SPACING
    end_bounds = end_node.setdefault("_temp", {}).setdefault(
        "bounds", {"width": 360, "height": 112}
    )
    end_bounds.update({"x": float(end_position["x"]) - 180.0, "y": old_end_y})
    _append_end_outputs(end_node, recorder_id)

    edges = workflow["json"]["edges"]
    end_edges = [edge for edge in edges if str(edge.get("targetNodeID")) == END_NODE_ID]
    if not end_edges:
        raise ValueError("原工作流 End 节点没有入边")
    edges[:] = [edge for edge in edges if str(edge.get("targetNodeID")) != END_NODE_ID]
    for edge in end_edges:
        bridged = copy.deepcopy(edge)
        bridged["targetNodeID"] = recorder_id
        edges.append(bridged)
    edges.append({"sourceNodeID": recorder_id, "targetNodeID": END_NODE_ID})
    workflow["json"]["nodes"].append(recorder)

    bounds = workflow.get("bounds")
    if isinstance(bounds, dict):
        left = float(bounds.get("x") or 0.0)
        old_right = left + float(bounds.get("width") or 0.0)
        bounds["width"] = max(old_right, float(end_position["x"]) + 320.0) - left

    return {
        "calls": [
            {
                "call_id": spec["call_id"],
                "tool": spec["tool"],
                "node_id": spec["node_id"],
                "item_input_name": (
                    None if spec["batch"] else f"in_{spec['call_id']}"
                ),
                "batch_source_input_name": (
                    f"batch_{spec['call_id']}_{spec['batch']['source_name']}"
                    if spec["batch"]
                    else None
                ),
                "batch_source_path": (
                    spec["batch"]["source_path"] if spec["batch"] else ""
                ),
                "batch_input_names": (
                    [
                        f"batch_{spec['call_id']}_{batch_name}"
                        for batch_name in spec["batch"]["refs"]
                    ]
                    if spec["batch"]
                    else []
                ),
                "dynamic_input_names": {
                    field: f"arg_{spec['call_id']}_{field}"
                    for field in ((spec.get("dynamic_refs") or {}) if not spec["batch"] else {})
                },
                "segment_input_name": (
                    f"segments_{spec['call_id']}" if spec["segment_output_name"] else None
                ),
            }
            for spec in specs
        ],
        "draft": draft_cfg,
        "recorder_node_id": recorder_id,
        "recorder_node_count": 1,
        "preserved_plugin_workflow": True,
    }


def generate_recorded_workflow(
    source_path: Path | str,
    output_path: Path | str,
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> dict[str, Any]:
    source = Path(source_path)
    output = Path(output_path)
    workflow = json.loads(source.read_text(encoding="utf-8"))
    report = add_draft_key_recorder(
        workflow,
        workflow_name=workflow_name,
        draft_name=draft_name,
        run_prefix=run_prefix,
    )
    output.write_text(
        json.dumps(workflow, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return {"output": str(output), **report}
