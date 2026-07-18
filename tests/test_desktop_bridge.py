import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from desktop_bridge.core import BridgeError, extract_draft_key, import_draft_payload


class DesktopBridgeTests(unittest.TestCase):
    def test_extracts_nested_coze_draft_key_string(self):
        key = {
            "kind": "jianying_draft_key",
            "meta": {"run_id": "nested-test"},
            "calls": [{"call_id": "image", "tool": "add_images", "params": {"image_infos": [{}]}}],
        }
        wrapped = {"data": {"output": {"draft_key": json.dumps(key, ensure_ascii=False)}}}
        self.assertEqual(extract_draft_key(wrapped), key)

    def test_rejects_payload_without_draft_key(self):
        with self.assertRaises(BridgeError):
            extract_draft_key({"status": "success"})

    def test_imports_and_verifies_local_draft(self):
        with tempfile.TemporaryDirectory(prefix="draft-bridge-test-") as temporary:
            root = Path(temporary)
            image_path = root / "image.png"
            Image.new("RGB", (320, 180), "#332211").save(image_path)
            key = {
                "kind": "jianying_draft_key",
                "meta": {"run_id": "bridge-unit-test", "title": "桥接测试"},
                "draft": {"width": 320, "height": 180, "name": "桥接测试"},
                "calls": [
                    {
                        "call_id": "image",
                        "tool": "add_images",
                        "params": {
                            "image_infos": [
                                {"image_url": str(image_path), "start": 0, "end": 1_000_000}
                            ]
                        },
                    }
                ],
            }
            report = import_draft_payload(key, draft_root=root / "drafts")
            self.assertTrue(report["verified"])
            self.assertEqual(report["track_count"], 1)
            self.assertEqual(report["segment_count"], 1)
            self.assertTrue((Path(report["draft_dir"]) / "draft_content.json").is_file())


if __name__ == "__main__":
    unittest.main()
