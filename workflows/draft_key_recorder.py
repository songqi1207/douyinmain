#!/usr/bin/env python3
"""Append a portable ``draft_key`` recorder to an intact Mihe workflow.

The original Mihe plugin nodes remain untouched.  A converted copy is used only
as a recipe for the recorder inputs and for any helper nodes that must produce
portable keyframes.  Those helpers are cloned under new ids and placed after the
original final plugin, immediately before the End node.
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from workflows.god.local_key import (
    AGGREGATE_NODE_ID,
    END_NODE_ID,
    convert_workflow_to_local_key,
)


RECORDER_NODE_ID = "390001"
RECORDER_HELPER_ID_START = 390100
_NODE_SPACING = 360.0


def _walk_block_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        if value.get("source") == "block-output" and value.get("blockID") is not None:
            refs.add(str(value["blockID"]))
        for child in value.values():
            refs.update(_walk_block_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_walk_block_refs(child))
    return refs


def _rewrite_block_refs(value: Any, id_map: dict[str, str]) -> None:
    if isinstance(value, dict):
        if value.get("source") == "block-output":
            block_id = str(value.get("blockID") or "")
            if block_id in id_map:
                value["blockID"] = id_map[block_id]
        for child in value.values():
            _rewrite_block_refs(child, id_map)
    elif isinstance(value, list):
        for child in value:
            _rewrite_block_refs(child, id_map)


def _same_node(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(
        right,
        ensure_ascii=False,
        sort_keys=True,
    )


def _required_helper_ids(
    original_nodes: dict[str, dict[str, Any]],
    converted_nodes: dict[str, dict[str, Any]],
    aggregate: dict[str, Any],
) -> set[str]:
    """Find converted-only or rewritten nodes needed by the aggregate node."""

    required: set[str] = set()
    queue = list(_walk_block_refs(aggregate))
    visited: set[str] = set()
    while queue:
        node_id = queue.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        converted = converted_nodes.get(node_id)
        if converted is None:
            continue
        original = original_nodes.get(node_id)
        if original is not None and _same_node(original, converted):
            continue
        required.add(node_id)
        queue.extend(_walk_block_refs(converted))
    return required


def _helper_order(helper_ids: set[str], converted_nodes: dict[str, dict[str, Any]]) -> list[str]:
    """Topologically order recorder helpers by their block-output references."""

    dependencies = {
        node_id: _walk_block_refs(converted_nodes[node_id]) & helper_ids
        for node_id in helper_ids
    }
    reverse: dict[str, set[str]] = defaultdict(set)
    indegree = {node_id: len(deps) for node_id, deps in dependencies.items()}
    for node_id, deps in dependencies.items():
        for dependency in deps:
            reverse[dependency].add(node_id)

    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for dependent in sorted(reverse[node_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    if len(ordered) != len(helper_ids):
        unresolved = sorted(helper_ids - set(ordered))
        raise ValueError(f"draft_key 记录辅助节点存在循环依赖: {unresolved}")
    return ordered


def _unique_numeric_id(nodes: dict[str, dict[str, Any]], preferred: int) -> str:
    candidate = preferred
    while str(candidate) in nodes:
        candidate += 1
    return str(candidate)


def _end_input_parameters(end_node: dict[str, Any]) -> list[dict[str, Any]]:
    return ((end_node.get("data") or {}).get("inputs") or {}).setdefault("inputParameters", [])


def _append_end_outputs(end_node: dict[str, Any], recorder_id: str) -> None:
    parameters = _end_input_parameters(end_node)
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


def _place_recorder_nodes(
    workflow: dict[str, Any],
    helper_nodes: list[dict[str, Any]],
    aggregate: dict[str, Any],
    end_node: dict[str, Any],
) -> None:
    end_meta = end_node.setdefault("meta", {})
    end_position = end_meta.setdefault("position", {"x": 0.0, "y": 0.0})
    start_x = float(end_position.get("x") or 0.0)
    y = float(end_position.get("y") or 0.0)

    recorder_nodes = [*helper_nodes, aggregate]
    for index, node in enumerate(recorder_nodes):
        node.setdefault("meta", {})["position"] = {
            "x": start_x + _NODE_SPACING * index,
            "y": y,
        }
    end_position["x"] = start_x + _NODE_SPACING * len(recorder_nodes)

    bounds = workflow.get("bounds")
    if isinstance(bounds, dict):
        left = float(bounds.get("x") or 0.0)
        old_right = left + float(bounds.get("width") or 0.0)
        new_right = max(old_right, float(end_position["x"]) + 320.0)
        bounds["width"] = new_right - left


def add_draft_key_recorder(
    workflow: dict[str, Any],
    *,
    workflow_name: str,
    draft_name: str,
    run_prefix: str,
) -> dict[str, Any]:
    """Mutate an original Mihe workflow by appending a sidecar recorder.

    All existing nodes except the End node remain byte-for-byte equivalent.  All
    existing edges except edges entering End remain unchanged.
    """

    original_nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
    if END_NODE_ID not in original_nodes:
        raise ValueError(f"工作流缺少 End 节点 {END_NODE_ID}")

    converted = copy.deepcopy(workflow)
    conversion = convert_workflow_to_local_key(
        converted,
        workflow_name=workflow_name,
        draft_name=draft_name,
        run_prefix=run_prefix,
    )
    converted_nodes = {str(node["id"]): node for node in converted["json"]["nodes"]}
    aggregate_recipe = converted_nodes[AGGREGATE_NODE_ID]

    helper_ids = _required_helper_ids(original_nodes, converted_nodes, aggregate_recipe)
    ordered_helper_ids = _helper_order(helper_ids, converted_nodes)

    occupied = dict(original_nodes)
    recorder_id = _unique_numeric_id(occupied, int(RECORDER_NODE_ID))
    occupied[recorder_id] = {}
    id_map: dict[str, str] = {}
    next_helper_id = RECORDER_HELPER_ID_START
    for old_id in ordered_helper_ids:
        new_id = _unique_numeric_id(occupied, next_helper_id)
        occupied[new_id] = {}
        id_map[old_id] = new_id
        next_helper_id = int(new_id) + 1

    helper_nodes: list[dict[str, Any]] = []
    for old_id in ordered_helper_ids:
        cloned = copy.deepcopy(converted_nodes[old_id])
        cloned["id"] = id_map[old_id]
        _rewrite_block_refs(cloned, id_map)
        cloned.setdefault("data", {})["title"] = f"draft_key记录辅助节点/{old_id}"
        helper_nodes.append(cloned)

    aggregate = copy.deepcopy(aggregate_recipe)
    aggregate["id"] = recorder_id
    _rewrite_block_refs(aggregate, id_map)
    aggregate.setdefault("data", {})["title"] = "记录 draft_key（不影响米核草稿）"

    end_node = original_nodes[END_NODE_ID]
    _append_end_outputs(end_node, recorder_id)
    _place_recorder_nodes(workflow, helper_nodes, aggregate, end_node)

    edges = workflow["json"]["edges"]
    end_edges = [edge for edge in edges if str(edge.get("targetNodeID")) == END_NODE_ID]
    if not end_edges:
        raise ValueError("原工作流 End 节点没有入边")
    edges[:] = [edge for edge in edges if str(edge.get("targetNodeID")) != END_NODE_ID]

    chain_ids = [node["id"] for node in helper_nodes] + [recorder_id]
    first_id = chain_ids[0]
    for edge in end_edges:
        bridged = copy.deepcopy(edge)
        bridged["targetNodeID"] = first_id
        edges.append(bridged)
    for source_id, target_id in zip(chain_ids, chain_ids[1:]):
        edges.append({"sourceNodeID": source_id, "targetNodeID": target_id})
    edges.append({"sourceNodeID": recorder_id, "targetNodeID": END_NODE_ID})

    workflow["json"]["nodes"].extend(helper_nodes)
    workflow["json"]["nodes"].append(aggregate)
    return {
        **conversion,
        "recorder_node_id": recorder_id,
        "helper_node_ids": id_map,
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
    """Load a workflow file, append the recorder, and write a new version."""

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
