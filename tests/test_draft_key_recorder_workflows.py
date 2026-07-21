import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.build_recorded_draft_key_workflows import PROFILES, build_all
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
                self.assertEqual([item["name"] for item in parameters], ["output", "draft_id", "draft_key"])
                self.assertEqual(
                    parameters[0]["input"]["value"]["content"],
                    parameters[1]["input"]["value"]["content"],
                )
                self.assertEqual(
                    parameters[2]["input"]["value"]["content"]["blockID"],
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
                        value = [{"audio_url": "voice.wav", "start": 0, "end": 1_000_000}]
                    elif tool == "add_images":
                        value = [{"image_url": "frame.png", "start": 0, "end": 1_000_000}]
                        last_image_segment_id = f"segment-{call['call_id']}"
                    elif tool == "add_captions":
                        value = [{"text": "draft_key", "start": 0, "end": 1_000_000}]
                    elif tool == "add_effects":
                        value = [{"effect": "柔光", "start": 0, "end": 1_000_000}]
                    else:
                        value = [
                            {
                                "segment_id": last_image_segment_id,
                                "property": "KFTypePositionX",
                                "offset": 0,
                                "value": 0,
                            }
                        ]
                    params[f"in_{call['call_id']}"] = json.dumps(value, ensure_ascii=False)
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
                keyframe_items = [
                    item
                    for call in key["calls"]
                    if call["tool"] == "add_keyframes"
                    for item in call["params"]["keyframes"]
                ]
                self.assertTrue(keyframe_items)
                self.assertTrue(all("segment_ref" in item for item in keyframe_items))

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
