import asyncio
import json
import tempfile
import unittest
import uuid
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import utils.draft_key_importer as draft_importer
from desktop_bridge.core import import_draft_payload
from workflows.cigarette import generate_cigarette_workflow
from workflows.god.local_key import convert_workflow_to_local_key, generate_local_key_workflow


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PROFILES = [
    (ROOT / "书单工作流模板_荐书-v1.json", "书单工作流_本地草稿", "书单_测试", "book_local_", 16),
    (ROOT / "每天认识一款香烟_中华_20260708_121403.txt", "香烟工作流_本地草稿", "香烟_测试", "cigarette_local_", 29),
    (ROOT / "神工作流模板_修改版-开场静态修正-v7.json", "神工作流模板_本地草稿", "神话解说_测试", "god_local_", 17),
]


def _aggregate_node(workflow: dict) -> dict:
    return next(node for node in workflow["json"]["nodes"] if str(node.get("id")) == "300201")


def _run_aggregate(workflow: dict, params: dict) -> dict:
    code = _aggregate_node(workflow)["data"]["inputs"]["code"]
    namespace = {"Args": SimpleNamespace, "Output": dict}
    exec(code, namespace)
    result = asyncio.run(namespace["main"](SimpleNamespace(params=params)))
    return json.loads(result["draft_key"])


def _run_code_node(node: dict, params: dict) -> dict:
    namespace = {"Args": SimpleNamespace, "Output": dict}
    exec(node["data"]["inputs"]["code"], namespace)
    return asyncio.run(namespace["main"](SimpleNamespace(params=params)))


class GodLocalKeyWorkflowTests(unittest.TestCase):
    def test_generated_workflow_returns_draft_key_without_dangling_references(self):
        with tempfile.TemporaryDirectory(prefix="local-key-workflows-") as temporary:
            for source, workflow_name, draft_name, run_prefix, expected_calls in TEMPLATE_PROFILES:
                with self.subTest(source=source.name):
                    output = Path(temporary) / f"{run_prefix}.json"
                    report = generate_local_key_workflow(
                        source,
                        output,
                        workflow_name=workflow_name,
                        draft_name=draft_name,
                        run_prefix=run_prefix,
                    )
                    workflow = json.loads(output.read_text(encoding="utf-8"))

                    self.assertEqual(len(report["calls"]), expected_calls)
                    end = next(node for node in workflow["json"]["nodes"] if str(node.get("id")) == "900001")
                    parameters = end["data"]["inputs"]["inputParameters"]
                    self.assertEqual([item["name"] for item in parameters], ["draft_key"])
                    self.assertEqual(parameters[0]["input"]["value"]["content"]["blockID"], "300201")

                    all_ids = set()
                    references = []

                    def walk(value):
                        if isinstance(value, dict):
                            if value.get("id") is not None and ("data" in value or "blocks" in value):
                                all_ids.add(str(value["id"]))
                            if value.get("source") == "block-output" and value.get("blockID"):
                                references.append(str(value["blockID"]))
                            for child in value.values():
                                walk(child)
                        elif isinstance(value, list):
                            for child in value:
                                walk(child)

                    walk(workflow)
                    self.assertEqual([block_id for block_id in references if block_id not in all_ids], [])

    def test_aggregate_output_can_create_a_real_local_jianying_draft(self):
        with tempfile.TemporaryDirectory(prefix="workflow-draft-import-") as temporary:
            root = Path(temporary)
            image_path = root / "frame.png"
            Image.new("RGB", (320, 180), "#332211").save(image_path)
            audio_path = root / "voice.wav"
            with wave.open(str(audio_path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 8000)

            samples = {
                "add_audios": {"audio_url": str(audio_path), "start": 0, "end": 1_000_000},
                "add_images": {"image_url": str(image_path), "start": 0, "end": 1_000_000},
                "add_captions": {"text": "draft_key 可用性验证", "start": 0, "end": 1_000_000},
                "add_effects": {"effect": "柔光", "start": 0, "end": 1_000_000},
            }
            for source, workflow_name, draft_name, run_prefix, expected_calls in TEMPLATE_PROFILES:
                with self.subTest(source=source.name):
                    workflow_path = root / f"{run_prefix}.json"
                    report = generate_local_key_workflow(
                        source,
                        workflow_path,
                        workflow_name=workflow_name,
                        draft_name=draft_name,
                        run_prefix=run_prefix,
                    )
                    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
                    nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
                    params = {}
                    for call in report["calls"]:
                        if call["tool"] == "add_keyframes":
                            source_id = call["ref"].split(".", 1)[0]
                            value = _run_code_node(
                                nodes[source_id],
                                {
                                    "image_infos": json.dumps([samples["add_images"]], ensure_ascii=False),
                                    "value_rows": ["-100|100"],
                                    "offset_rows": "0|100",
                                },
                            )["keyframes"]
                        else:
                            value = json.dumps([samples[call["tool"]]], ensure_ascii=False)
                        params[f"in_{call['call_id']}"] = value
                    key = _run_aggregate(workflow, params)

                    dry_run = draft_importer.import_draft_key(key, dry_run=True)
                    self.assertEqual(dry_run["message"], "ok")
                    self.assertEqual(len(dry_run["calls"]), expected_calls)

                    with (
                        patch.object(draft_importer, "_CACHE_DIR", root / f"{run_prefix}-cache"),
                        patch.object(draft_importer, "_REGISTRY_PATH", root / f"{run_prefix}-imports.json"),
                        patch.object(draft_importer, "_RENDER_KEYS_DIR", root / f"{run_prefix}-render-keys"),
                    ):
                        imported = import_draft_payload(key, draft_root=root / f"{run_prefix}-drafts")

                    self.assertTrue(imported["verified"])
                    self.assertGreater(imported["track_count"], 0)
                    self.assertGreater(imported["segment_count"], 0)
                    draft_dir = Path(imported["draft_dir"])
                    self.assertTrue((draft_dir / "draft_content.json").is_file())
                    self.assertTrue((draft_dir / "draft_meta_info.json").is_file())
                    self.assertEqual(draft_dir.name, imported["draft_name"])
                    self.assertEqual(draft_dir.name, imported["draft_id"])
                    self.assertEqual(str(uuid.UUID(imported["draft_id"])).upper(), imported["draft_id"])

                    draft_content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
                    draft_meta = json.loads((draft_dir / "draft_meta_info.json").read_text(encoding="utf-8"))
                    self.assertEqual(draft_meta["draft_id"], imported["draft_id"])
                    self.assertEqual(draft_meta["draft_name"], draft_dir.name)
                    for material_type in ("audios", "videos"):
                        for material in draft_content["materials"][material_type]:
                            material_path = Path(material["path"])
                            self.assertTrue(material_path.is_file())
                            self.assertIn(draft_dir.resolve(), material_path.resolve().parents)

    def test_every_draft_uses_its_uuid_as_folder_and_display_name(self):
        with tempfile.TemporaryDirectory(prefix="workflow-draft-names-") as temporary:
            from utils.jianying_drafts import create_draft, get_draft_info

            draft_name = "\u4e66\u5355_\u672c\u5730\u8349\u7a3f"
            with patch.dict("os.environ", {"JIANYING_DRAFT_ROOT": temporary}):
                first = create_draft(1080, 1920, draft_name)
                second = create_draft(1080, 1920, draft_name)

                self.assertEqual(Path(first["draft_dir"]).name, first["draft_id"])
                self.assertEqual(Path(second["draft_dir"]).name, second["draft_id"])
                self.assertEqual(first["draft_name"], first["draft_id"])
                self.assertEqual(second["draft_name"], second["draft_id"])
                self.assertEqual(first["requested_name"], draft_name)
                self.assertEqual(second["requested_name"], draft_name)
                self.assertNotEqual(first["draft_id"], second["draft_id"])
                self.assertEqual(get_draft_info(first["draft_id"])["draft_dir"], first["draft_dir"])
                self.assertEqual(get_draft_info(second["draft_id"])["draft_dir"], second["draft_dir"])

    def test_dynamic_cigarette_batch_images_and_keyframes_produce_importable_key(self):
        workflow, _warning = generate_cigarette_workflow("红塔山")
        report = convert_workflow_to_local_key(
            workflow,
            workflow_name="香烟工作流_本地草稿",
            draft_name="香烟_红塔山",
            run_prefix="cigarette_local_",
        )
        nodes = {str(node["id"]): node for node in workflow["json"]["nodes"]}
        image = {"image_url": "frame.png", "start": 0, "end": 1_000_000}
        batch_images = _run_code_node(
            nodes["151678"],
            {
                "batch_item1": [json.dumps([image])] * 8,
                "batch_output": [-2800, -2100, -1400, -700, 0, 700, 1400, 2100],
            },
        )["image_infos"]
        batch_keyframes = _run_code_node(
            nodes["153503"],
            {
                "image_infos": batch_images,
                "value_rows": ["-100|100"] * 8,
                "offset_rows": "0|100",
            },
        )["keyframes"]
        self.assertEqual(len(json.loads(batch_images)), 8)
        self.assertEqual(len(json.loads(batch_keyframes)), 16)

        samples = {
            "add_audios": {"audio_url": "voice.wav", "start": 0, "end": 1_000_000},
            "add_images": image,
            "add_captions": {"text": "香烟工作流验证", "start": 0, "end": 1_000_000},
            "add_effects": {"effect": "柔光", "start": 0, "end": 1_000_000},
        }
        params = {}
        for call in report["calls"]:
            if call["call_id"] == "call_151678":
                value = batch_images
            elif call["tool"] == "add_keyframes":
                source_id = call["ref"].split(".", 1)[0]
                value = (
                    batch_keyframes
                    if source_id == "153503"
                    else _run_code_node(
                        nodes[source_id],
                        {"image_infos": json.dumps([image], ensure_ascii=False)},
                    )["keyframes"]
                )
            else:
                value = json.dumps([samples[call["tool"]]], ensure_ascii=False)
            params[f"in_{call['call_id']}"] = value

        key = _run_aggregate(workflow, params)
        dry_run = draft_importer.import_draft_key(key, dry_run=True)
        self.assertEqual(dry_run["message"], "ok")
        self.assertEqual(len(dry_run["calls"]), 29)


if __name__ == "__main__":
    unittest.main()
