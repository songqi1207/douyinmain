import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.build_recorded_draft_key_workflows import PROFILES, build_all
from utils.draft_key_importer import _merge_global_image_style
from utils.draft_key_importer import import_draft_key
from workflows.draft_key_recorder import add_draft_key_recorder
from workflows.cigarette import generate_cigarette_workflow
from workflows.god.local_key import _api_name


def _edge_key(edge: dict) -> tuple[str, str, str]:
    return (
        str(edge.get("sourceNodeID")),
        str(edge.get("targetNodeID")),
        str(edge.get("sourcePortID") or ""),
    )


def _run_aggregate(node: dict, params: dict) -> dict:
    namespace = {"Args": SimpleNamespace, "Output": dict}
    exec(node["data"]["inputs"]["code"], namespace)
    result = asyncio.run(namespace["main"](SimpleNamespace(params=params)))
    return json.loads(result["draft_key"])


class DraftKeyRecorderWorkflowTests(unittest.TestCase):
    def test_importer_applies_all_node_level_image_style_fields(self):
        params = {
            "alpha": 0.8,
            "scale_x": 1.12,
            "scale_y": 1.13,
            "transform_x": -42,
            "transform_y": 96,
            "in_animation": "渐显",
            "in_animation_duration": 300_000,
            "out_animation": "渐隐",
            "out_animation_duration": 400_000,
        }
        merged = _merge_global_image_style(
            [{"image_url": "frame.png", "scale_x": 2}],
            params,
        )

        self.assertEqual(merged[0]["scale_x"], 2)
        for name, value in params.items():
            if name != "scale_x":
                self.assertEqual(merged[0][name], value)

    def test_original_plugins_and_edges_are_preserved(self):
        for profile in PROFILES:
            with self.subTest(source=profile["source"].name):
                original = json.loads(profile["source"].read_text(encoding="utf-8"))
                recorded = copy.deepcopy(original)
                report = add_draft_key_recorder(
                    recorded,
                    workflow_name=profile["workflow_name"],
                    draft_name=profile["draft_name"],
                    run_prefix=profile["run_prefix"],
                )

                original_nodes = {str(node["id"]): node for node in original["json"]["nodes"]}
                recorded_nodes = {str(node["id"]): node for node in recorded["json"]["nodes"]}
                for node_id, node in original_nodes.items():
                    if node_id == "900001":
                        continue
                    self.assertEqual(recorded_nodes[node_id], node)

                original_plugins = {
                    node_id: _api_name(node)
                    for node_id, node in original_nodes.items()
                    if _api_name(node)
                }
                recorded_plugins = {
                    node_id: _api_name(recorded_nodes[node_id])
                    for node_id in original_plugins
                }
                self.assertEqual(recorded_plugins, original_plugins)

                original_edges = {
                    _edge_key(edge)
                    for edge in original["json"]["edges"]
                    if str(edge.get("targetNodeID")) != "900001"
                }
                recorded_edges = {_edge_key(edge) for edge in recorded["json"]["edges"]}
                self.assertTrue(original_edges.issubset(recorded_edges))
                self.assertTrue(report["preserved_plugin_workflow"])
                self.assertEqual(report["recorder_node_count"], 1)
                self.assertEqual(len(recorded_nodes), len(original_nodes) + 1)
                self.assertEqual(len(recorded["json"]["edges"]), len(original["json"]["edges"]) + 1)

                recorder = recorded_nodes[report["recorder_node_id"]]
                self.assertIn("nodeMeta", recorder["data"])
                self.assertIn("_temp", recorder)
                self.assertIn("externalData", recorder["_temp"])
                recorder_position = recorder["meta"]["position"]
                recorder_bounds = recorder["_temp"]["bounds"]
                self.assertEqual(recorder_bounds["x"], recorder_position["x"] - 180)
                self.assertEqual(recorder_bounds["y"], recorder_position["y"])

                end = recorded_nodes["900001"]
                end_position = end["meta"]["position"]
                end_bounds = end["_temp"]["bounds"]
                self.assertEqual(end_bounds["x"], end_position["x"] - 180)
                self.assertEqual(end_bounds["y"], end_position["y"])

                list_inputs = [
                    item["input"]
                    for item in recorder["data"]["inputs"]["inputParameters"]
                    if item["input"]["type"] == "list"
                ]
                self.assertTrue(list_inputs)
                self.assertTrue(all(isinstance(item.get("schema"), dict) for item in list_inputs))
                self.assertTrue(
                    all(item["value"]["rawMeta"]["type"] in {99, 103} for item in list_inputs)
                )

    def test_end_returns_legacy_output_draft_id_and_draft_key(self):
        for profile in PROFILES:
            with self.subTest(source=profile["source"].name):
                workflow = json.loads(profile["source"].read_text(encoding="utf-8"))
                report = add_draft_key_recorder(
                    workflow,
                    workflow_name=profile["workflow_name"],
                    draft_name=profile["draft_name"],
                    run_prefix=profile["run_prefix"],
                )
                nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
                end = nodes["900001"]
                parameters = end["data"]["inputs"]["inputParameters"]
                names = [item["name"] for item in parameters]
                self.assertEqual(names[-2:], ["draft_id", "draft_key"])
                self.assertIn("output", names)
                self.assertEqual(
                    parameters[0]["input"]["value"]["content"],
                    parameters[-2]["input"]["value"]["content"],
                )
                self.assertEqual(
                    parameters[-1]["input"]["value"]["content"]["blockID"],
                    report["recorder_node_id"],
                )

    def test_recorder_emits_an_importable_portable_key(self):
        for profile in PROFILES:
            with self.subTest(source=profile["source"].name):
                workflow = json.loads(profile["source"].read_text(encoding="utf-8"))
                report = add_draft_key_recorder(
                    workflow,
                    workflow_name=profile["workflow_name"],
                    draft_name=profile["draft_name"],
                    run_prefix=profile["run_prefix"],
                )
                nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
                aggregate = nodes[report["recorder_node_id"]]

                params = {}
                last_image_segment_id = ""
                for call in report["calls"]:
                    tool = call["tool"]
                    if tool == "add_audios":
                        value = [{
                            "audio_url": "voice.wav",
                            "start": 0,
                            "end": 1_000_000,
                            "volume": 0.35,
                            "audio_effect": "人声增强3",
                        }]
                    elif tool == "add_images":
                        value = [{
                            "image_url": "frame.png",
                            "start": 0,
                            "end": 1_000_000,
                            "alpha": 0.8,
                            "scale_x": 1.2,
                            "scale_y": 1.1,
                            "transform_x": -42,
                            "transform_y": 96,
                            "rotation": 12,
                            "in_animation": "渐显",
                            "in_animation_duration": 300_000,
                        }]
                        last_image_segment_id = f"segment-{call['call_id']}"
                    elif tool == "add_captions":
                        value = [{
                            "text": "draft_key",
                            "start": 0,
                            "end": 1_000_000,
                            "font": "出云龙",
                            "font_size": 15,
                            "transform_x": -58,
                            "transform_y": 100,
                            "in_animation": "滚入",
                            "in_animation_duration": 112_800,
                        }]
                    elif tool == "add_effects":
                        value = [{
                            "effect": "柔光",
                            "start": 0,
                            "end": 1_000_000,
                            "intensity": 0.8,
                            "adjust_params": {"effects_adjust_filter": 0.7},
                        }]
                    else:
                        value = [
                            {
                                "segment_id": last_image_segment_id,
                                "property": "KFTypePositionX",
                                "offset": 0,
                                "value": 0,
                            }
                        ]
                    if call["item_input_name"]:
                        params[call["item_input_name"]] = json.dumps(value, ensure_ascii=False)
                    elif call["batch_source_input_name"]:
                        source_value = value
                        for part in reversed(
                            [part for part in call["batch_source_path"].split(".") if part]
                        ):
                            source_value = {part: source_value}
                        params[call["batch_source_input_name"]] = [source_value]
                        for input_name in call["batch_input_names"]:
                            params.setdefault(input_name, [0])
                    if call["segment_input_name"]:
                        segment_id = (
                            last_image_segment_id
                            if tool == "add_images"
                            else f"segment-{call['call_id']}"
                        )
                        params[call["segment_input_name"]] = [{"id": segment_id}]

                key = _run_aggregate(aggregate, params)
                validation = import_draft_key(key, dry_run=True)
                self.assertEqual(validation["message"], "ok")
                self.assertEqual(len(validation["calls"]), len(report["calls"]))
                self.assertEqual(key["meta"]["unresolved_segment_ids"], [])
                self.assertEqual(key["meta"]["recorded_operation_count"], len(key["calls"]))
                self.assertEqual(key["meta"]["template_operation_count"], len(report["calls"]))
                self.assertEqual(len(key["meta"]["recorded_field_manifest"]), len(key["calls"]))
                expected_fields = {
                    "add_audios": {"audio_url", "start", "end", "volume", "audio_effect"},
                    "add_images": {
                        "image_url", "start", "end", "alpha", "scale_x", "scale_y",
                        "transform_x", "transform_y", "rotation", "in_animation",
                        "in_animation_duration",
                    },
                    "add_captions": {
                        "text", "start", "end", "font", "font_size", "transform_x",
                        "transform_y", "in_animation", "in_animation_duration",
                    },
                    "add_effects": {"effect", "start", "end", "intensity", "adjust_params"},
                }
                for manifest in key["meta"]["recorded_field_manifest"]:
                    if manifest["tool"] in expected_fields:
                        self.assertTrue(
                            expected_fields[manifest["tool"]].issubset(manifest["item_fields"])
                        )
                self.assertTrue(
                    all(call.get("source_node_id") for call in key["calls"])
                )
                for call in key["calls"]:
                    source = nodes[call["source_node_id"]]
                    for parameter in source["data"]["inputs"]["inputParameters"]:
                        name = parameter["name"]
                        value = parameter["input"].get("value") or {}
                        if name != "draft_id" and value.get("type") == "literal":
                            self.assertEqual(
                                call["params"].get(name),
                                value.get("content"),
                                f"{call['call_id']} lost literal parameter {name}",
                            )
                keyframe_items = [
                    item
                    for call in key["calls"]
                    if call["tool"] == "add_keyframes"
                    for item in call["params"]["keyframes"]
                ]
                self.assertTrue(keyframe_items)
                self.assertTrue(all("segment_ref" in item for item in keyframe_items))

    def test_recorder_captures_non_batch_dynamic_plugin_parameters(self):
        profile = PROFILES[0]
        workflow = json.loads(profile["source"].read_text(encoding="utf-8"))
        nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
        start = nodes["100001"]
        start["data"]["outputs"].append(
            {"type": "float", "name": "dynamic_scale", "required": False}
        )
        image_node = nodes["198946"]
        scale_x = next(
            item
            for item in image_node["data"]["inputs"]["inputParameters"]
            if item["name"] == "scale_x"
        )
        scale_x["input"]["value"] = {
            "type": "ref",
            "content": {
                "source": "block-output",
                "blockID": "100001",
                "name": "dynamic_scale",
            },
            "rawMeta": {"type": 4},
        }

        report = add_draft_key_recorder(
            workflow,
            workflow_name="动态参数记录测试",
            draft_name="动态参数记录测试",
            run_prefix="dynamic_fields_",
        )
        recorder = next(
            node for node in workflow["json"]["nodes"] if str(node["id"]) == report["recorder_node_id"]
        )
        call = next(item for item in report["calls"] if item["node_id"] == "198946")
        params = {
            call["item_input_name"]: json.dumps(
                [{"image_url": "frame.png", "start": 0, "end": 1_000_000}],
                ensure_ascii=False,
            ),
            call["dynamic_input_names"]["scale_x"]: 1.75,
        }
        key = _run_aggregate(recorder, params)

        self.assertEqual(len(key["calls"]), 1)
        self.assertEqual(key["calls"][0]["params"]["scale_x"], 1.75)
        manifest = key["meta"]["recorded_field_manifest"][0]
        self.assertIn("scale_x", manifest["parameter_fields"])
        self.assertEqual(
            set(manifest["item_fields"]),
            {"image_url", "start", "end"},
        )

    def test_recorder_omits_empty_optional_calls(self):
        profile = PROFILES[0]
        workflow = json.loads(profile["source"].read_text(encoding="utf-8"))
        report = add_draft_key_recorder(
            workflow,
            workflow_name=profile["workflow_name"],
            draft_name=profile["draft_name"],
            run_prefix=profile["run_prefix"],
        )
        nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
        aggregate = nodes[report["recorder_node_id"]]
        first_call = report["calls"][0]
        params = {
            f"in_{first_call['call_id']}": json.dumps(
                [{"audio_url": "voice.wav", "start": 0, "end": 1_000_000}],
                ensure_ascii=False,
            )
        }

        key = _run_aggregate(aggregate, params)

        self.assertEqual(len(key["calls"]), 1)
        self.assertEqual(key["calls"][0]["call_id"], first_call["call_id"])
        self.assertNotIn("call_191365", {call["call_id"] for call in key["calls"]})
        self.assertNotIn("call_300101", {call["call_id"] for call in key["calls"]})
        self.assertEqual(key["meta"]["template_operation_count"], len(report["calls"]))
        self.assertEqual(key["meta"]["recorded_operation_count"], 1)
        self.assertEqual(
            len(key["meta"]["skipped_empty_calls"]),
            len(report["calls"]) - 1,
        )
        self.assertEqual(import_draft_key(key, dry_run=True)["message"], "ok")

    def test_dynamic_cigarette_keeps_the_5fbf_generator_graph_and_adds_one_node(self):
        original, _warning = generate_cigarette_workflow("红塔山")
        recorded = copy.deepcopy(original)
        report = add_draft_key_recorder(
            recorded,
            workflow_name="香烟工作流_米核插件+draft_key记录",
            draft_name="香烟_红塔山",
            run_prefix="cigarette_recorded_",
        )
        original_nodes = {str(node["id"]): node for node in original["json"]["nodes"]}
        recorded_nodes = {str(node["id"]): node for node in recorded["json"]["nodes"]}
        self.assertEqual(len(report["calls"]), 29)
        self.assertEqual(report["recorder_node_count"], 1)
        self.assertEqual(len(recorded_nodes), len(original_nodes) + 1)
        self.assertEqual(len(recorded["json"]["edges"]), len(original["json"]["edges"]) + 1)
        for node_id, node in original_nodes.items():
            if node_id != "900001":
                self.assertEqual(recorded_nodes[node_id], node)

    def test_checked_in_v1_files_match_the_builder(self):
        with tempfile.TemporaryDirectory(prefix="recorded-workflows-") as temporary:
            backups = {}
            try:
                for profile in PROFILES:
                    output = profile["output"]
                    backups[output] = output.read_bytes() if output.exists() else None
                    profile["output"] = Path(temporary) / output.name
                reports = build_all()
                self.assertEqual(len(reports), 3)
                for profile, report in zip(PROFILES, reports):
                    generated = profile["output"].read_text(encoding="utf-8")
                    original_output = next(path for path in backups if path.name == profile["output"].name)
                    self.assertEqual(generated, original_output.read_text(encoding="utf-8"))
                    self.assertGreater(report["calls"], 0)
            finally:
                for profile in PROFILES:
                    temporary_output = profile["output"]
                    original_output = next(
                        (path for path in backups if path.name == temporary_output.name),
                        None,
                    )
                    if original_output is not None:
                        profile["output"] = original_output


if __name__ == "__main__":
    unittest.main()
