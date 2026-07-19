import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from desktop_bridge.core import (
    BridgeError,
    ensure_mihe_sync,
    export_mihe_server_draft_json,
    extract_draft_key,
    extract_mihe_draft_id,
    import_draft_payload,
    import_mihe_server_draft,
)


class DesktopBridgeTests(unittest.TestCase):
    def test_exports_raw_mihe_json_and_navigable_structure(self):
        with tempfile.TemporaryDirectory(prefix="mihe-export-test-") as temporary:
            payload = {
                "canvas_config": {"width": 1080, "height": 1920},
                "duration": 2_000_000,
                "materials": {
                    "videos": [{"id": "video-1", "path": "https://example.invalid/1.png", "type": "photo"}],
                    "video_effects": [{"id": "effect-1", "name": "glow"}],
                },
                "tracks": [
                    {
                        "id": "track-1",
                        "type": "video",
                        "segments": [
                            {
                                "id": "segment-1",
                                "material_id": "video-1",
                                "target_timerange": {"start": 0, "duration": 2_000_000},
                                "common_keyframes": [
                                    {"property_type": "KFTypePositionX", "keyframe_list": []}
                                ],
                            }
                        ],
                    }
                ],
            }
            report = export_mihe_server_draft_json(
                "fdee55ea-0ba9-484d-8e6a-1abcbaaad15b",
                output_dir=Path(temporary),
                server_payload=payload,
            )
            raw = json.loads(Path(report["raw_json_path"]).read_text(encoding="utf-8"))
            structure = json.loads(Path(report["structure_path"]).read_text(encoding="utf-8"))
            self.assertEqual(raw, payload)
            self.assertEqual(structure["track_count"], 1)
            self.assertEqual(structure["segment_count"], 1)
            segment = structure["tracks"][0]["segments"][0]
            self.assertEqual(segment["json_path"], "$.tracks[0].segments[0]")
            self.assertEqual(segment["material_json_path"], "$.materials.videos[0]")
            self.assertEqual(segment["keyframe_property_types"], ["KFTypePositionX"])

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

    def test_extracts_nested_mihe_draft_id(self):
        draft_id = "c7f3042a-6741-1bad-02a0-0f2ac1527e5f/36788c0f-70d0-4c8a-b77f-613c4173ff42"
        wrapped = {"data": {"output": {"draft_id": draft_id}}}
        self.assertEqual(extract_mihe_draft_id(wrapped), draft_id)

    def test_downloads_and_pins_official_mihe_sync_payload(self):
        with tempfile.TemporaryDirectory(prefix="mihe-sync-test-") as temporary:
            root = Path(temporary)
            payload = b"MZ" + (b"\0" * (1024 * 1024))
            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.writestr("米核剪映小助手.exe", payload)
            archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
            executable_hash = hashlib.sha256(payload).hexdigest()
            install_dir = root / "installed"

            executable = ensure_mihe_sync(
                base_dir=install_dir,
                download_url="https://example.invalid/mihe.zip",
                archive_sha256=archive_hash,
                executable_sha256=executable_hash,
                downloader=lambda _url, destination: shutil.copyfile(archive, destination),
            )

            self.assertEqual(executable.read_bytes(), payload)
            self.assertTrue((install_dir / "source.json").is_file())
            cached = ensure_mihe_sync(
                base_dir=install_dir,
                archive_sha256=archive_hash,
                executable_sha256=executable_hash,
                downloader=lambda _url, _destination: self.fail("cached executable should not download again"),
            )
            self.assertEqual(cached, executable)

    def test_directly_imports_mihe_server_draft_and_keeps_json_backup(self):
        with tempfile.TemporaryDirectory(prefix="mihe-direct-test-") as temporary:
            root = Path(temporary)
            draft_id = "fdee55ea-0ba9-484d-8e6a-1abcbaaad15b"
            payload = {
                "canvas_config": {"width": 1080, "height": 1920, "ratio": "9:16"},
                "duration": 0,
                "materials": {
                    "audios": [{"id": "audio-1", "path": "https://example.invalid/a.mp3"}],
                    "videos": [
                        {
                            "id": "video-1",
                            "path": "https://example.invalid/i.png",
                            "type": "photo",
                            "local_id": "",
                        }
                    ],
                },
                "tracks": [
                    {
                        "type": "video",
                        "segments": [
                            {
                                "target_timerange": {"start": 0, "duration": 2_000_000},
                                "common_keyframes": [
                                    {"property_type": "KFTypePositionX", "keyframe_list": [{"time_offset": 0}]},
                                    {
                                        "property_type": "KFTypePositionX",
                                        "keyframe_list": [{"time_offset": 2_000_000}],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }

            def fake_asset_download(_url: str, destination: Path) -> None:
                destination.write_bytes(b"asset")

            report = import_mihe_server_draft(
                draft_id,
                draft_root=root / "drafts",
                server_payload=payload,
                asset_downloader=fake_asset_download,
            )

            draft_dir = Path(report["draft_dir"])
            content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
            backup = json.loads((draft_dir / "mihe_server_draft.json").read_text(encoding="utf-8"))
            self.assertEqual(report["method"], "mihe_direct_http")
            self.assertEqual(report["asset_count"], 2)
            self.assertEqual(content["duration"], 2_000_000)
            self.assertEqual(len(content["tracks"][0]["segments"][0]["common_keyframes"]), 1)
            self.assertTrue(Path(content["materials"]["audios"][0]["path"]).is_file())
            self.assertTrue(Path(content["materials"]["videos"][0]["path"]).is_file())
            self.assertEqual(backup["materials"]["audios"][0]["path"], "https://example.invalid/a.mp3")
            self.assertTrue((root / "drafts" / "root_meta_info.json").is_file())

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
