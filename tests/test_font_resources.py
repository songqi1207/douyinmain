import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_bridge.device_agent import (
    FontResourceUnavailable,
    _run_pyjianying_export,
)
from desktop_bridge.font_resources import (
    bind_cached_fonts,
    build_font_preload_key,
    find_cached_font,
    inspect_font_resources,
    jianying_font_cache_roots,
    required_font_resources,
)


class JianyingFontResourceTests(unittest.TestCase):
    def test_catalog_contains_all_fonts_used_by_production_workflows(self):
        resources = required_font_resources()
        by_name = {item["name"]: item for item in resources}

        self.assertEqual(
            set(by_name),
            {"出云龙", "江湖体", "毛笔行楷", "思源粗宋", "高字标志黑"},
        )
        self.assertIn("华文行楷", by_name["毛笔行楷"]["aliases"])
        self.assertTrue(all(item["resource_id"].isdigit() for item in resources))

    def test_finds_font_in_cache_inferred_from_draft_root(self):
        with tempfile.TemporaryDirectory(prefix="jianying-font-cache-") as temporary:
            user_data = Path(temporary) / "JianyingPro" / "User Data"
            draft_root = user_data / "Projects" / "com.lveditor.draft"
            resource_id = "7618137748045696292"
            font_path = (
                user_data
                / "Cache"
                / "effect"
                / resource_id
                / "asset-hash"
                / "出云龙.ttf"
            )
            draft_root.mkdir(parents=True)
            font_path.parent.mkdir(parents=True)
            font_path.write_bytes(b"\x00\x01\x00\x00" + b"\0" * 2048)

            roots = jianying_font_cache_roots(draft_root)
            self.assertIn((user_data / "Cache" / "effect").resolve(), roots)
            self.assertEqual(
                find_cached_font(resource_id, draft_root=draft_root),
                font_path.resolve(),
            )

    def test_preload_key_contains_explicit_resource_ids(self):
        selected = required_font_resources()[:2]
        key = build_font_preload_key(selected)

        self.assertEqual(key["kind"], "jianying_draft_key")
        self.assertEqual(len(key["calls"]), 2)
        self.assertEqual(
            key["calls"][0]["params"]["font_resource_id"],
            selected[0]["resource_id"],
        )
        self.assertEqual(key["calls"][0]["params"]["font"], selected[0]["name"])

    def test_binds_cached_font_path_and_reports_missing_names(self):
        with tempfile.TemporaryDirectory(prefix="jianying-font-binding-") as temporary:
            root = Path(temporary)
            draft_root = root / "User Data" / "Projects" / "com.lveditor.draft"
            draft_dir = draft_root / "DRAFT-ID"
            draft_dir.mkdir(parents=True)
            cached_root = root / "User Data" / "Cache" / "effect"
            available_id = "7618137748045696292"
            cached_font = cached_root / available_id / "hash" / "出云龙.ttf"
            cached_font.parent.mkdir(parents=True)
            cached_font.write_bytes(b"OTTO" + b"\0" * 2048)
            content = {
                "materials": {
                    "texts": [
                        {
                            "id": "text-1",
                            "font_name": "出云龙",
                            "content": json.dumps(
                                {
                                    "styles": [
                                        {
                                            "font": {
                                                "id": available_id,
                                                "path": "D:",
                                            }
                                        }
                                    ],
                                    "text": "盘古",
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ]
                }
            }
            content_path = draft_dir / "draft_content.json"
            content_path.write_text(
                json.dumps(content, ensure_ascii=False),
                encoding="utf-8",
            )
            resources = [
                {"name": "出云龙", "resource_id": available_id},
                {"name": "江湖体", "resource_id": "7080097079397192228"},
            ]

            result = bind_cached_fonts(
                draft_dir,
                resources,
                draft_root=draft_root,
            )
            updated = json.loads(content_path.read_text(encoding="utf-8"))
            material = updated["materials"]["texts"][0]
            style = json.loads(material["content"])["styles"][0]

            self.assertEqual(result["bound"], ["出云龙"])
            self.assertEqual(result["missing"], ["江湖体"])
            self.assertEqual(style["font"]["path"], str(cached_font.resolve()))
            self.assertEqual(material["font_path"], str(cached_font.resolve()))
            self.assertEqual(material["font_resource_id"], available_id)

    def test_inspection_does_not_treat_resource_id_as_downloaded_file(self):
        with tempfile.TemporaryDirectory(prefix="jianying-font-missing-") as temporary:
            statuses = inspect_font_resources(
                [{"name": "出云龙", "resource_id": "7618137748045696292"}],
                cache_roots=[Path(temporary)],
            )

        self.assertFalse(statuses[0]["available"])
        self.assertEqual(statuses[0]["cached_path"], "")

    @patch("pyJianYingDraft.JianyingController")
    def test_native_export_stops_when_font_did_not_reach_cache(
        self,
        controller_type,
    ):
        with tempfile.TemporaryDirectory(prefix="jianying-font-export-gate-") as temporary:
            root = Path(temporary)
            executable = root / "JianyingPro.exe"
            executable.write_bytes(b"MZ")
            draft_root = root / "User Data" / "Projects" / "com.lveditor.draft"
            draft_dir = draft_root / "DRAFT-ID"
            draft_dir.mkdir(parents=True)

            with self.assertRaises(FontResourceUnavailable) as raised:
                _run_pyjianying_export(
                    "DRAFT-ID",
                    root / "output.mp4",
                    executable,
                    900,
                    "job-id",
                    resource_wait_seconds=0,
                    draft_dir=draft_dir,
                    draft_root=draft_root,
                    font_resources=[
                        {
                            "name": "出云龙",
                            "resource_id": "7618137748045696292",
                        }
                    ],
                )

        self.assertIn("出云龙", str(raised.exception))
        controller_type.return_value.export_draft.assert_not_called()


if __name__ == "__main__":
    unittest.main()
