import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_bridge.device_agent import (
    FontResourceUnavailable,
    _prepare_export_fonts,
    _run_pyjianying_export,
)
from desktop_bridge.font_resources import (
    bind_cached_fonts,
    build_font_preload_key,
    fallback_missing_fonts_to_default,
    find_bound_font,
    find_bound_font_in_draft_library,
    find_cached_font,
    find_system_font,
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

    @patch.dict("os.environ", {"WINDIR": ""})
    def test_unavailable_cloud_font_falls_back_to_jianying_default(self):
        with tempfile.TemporaryDirectory(prefix="jianying-font-fallback-") as temporary:
            root = Path(temporary)
            draft_root = root / "User Data" / "Projects" / "com.lveditor.draft"
            draft_dir = draft_root / "DRAFT-ID"
            draft_dir.mkdir(parents=True)
            resource_id = "6912033793700270606"
            content_path = draft_dir / "draft_content.json"
            content_path.write_text(
                json.dumps(
                    {
                        "materials": {
                            "texts": [
                                {
                                    "id": "text-1",
                                    "font_name": "毛笔行楷",
                                    "font_resource_id": resource_id,
                                    "font_path": "D:",
                                    "fonts": [{"resource_id": resource_id}],
                                    "content": json.dumps(
                                        {
                                            "styles": [
                                                {
                                                    "font": {
                                                        "id": resource_id,
                                                        "path": "D:",
                                                    },
                                                    "size": 12,
                                                }
                                            ],
                                            "text": "真正的自由",
                                        },
                                        ensure_ascii=False,
                                    ),
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = fallback_missing_fonts_to_default(
                draft_dir,
                [{"name": "毛笔行楷", "resource_id": resource_id}],
                draft_root=draft_root,
                cache_roots=[root / "empty-cache"],
            )
            material = json.loads(content_path.read_text(encoding="utf-8"))["materials"]["texts"][0]
            style = json.loads(material["content"])["styles"][0]

            self.assertEqual(result["fallback"], ["毛笔行楷"])
            self.assertEqual(result["changed_materials"], 1)
            self.assertNotIn("font", style)
            self.assertNotIn("font_name", material)
            self.assertNotIn("font_resource_id", material)
            self.assertNotIn("fonts", material)

    def test_available_cloud_font_is_not_replaced(self):
        with tempfile.TemporaryDirectory(prefix="jianying-font-no-fallback-") as temporary:
            root = Path(temporary)
            draft_dir = root / "draft"
            draft_dir.mkdir()
            resource_id = "6912033793700270606"
            font_path = root / "毛笔行楷.ttf"
            font_path.write_bytes(b"OTTO" + b"\0" * 2048)
            content_path = draft_dir / "draft_content.json"
            content_path.write_text(
                json.dumps(
                    {
                        "materials": {
                            "texts": [
                                {
                                    "font_name": "毛笔行楷",
                                    "font_resource_id": resource_id,
                                    "font_path": str(font_path),
                                    "content": json.dumps(
                                        {"styles": [{"font": {"id": resource_id, "path": str(font_path)}}], "text": "字幕"},
                                        ensure_ascii=False,
                                    ),
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = fallback_missing_fonts_to_default(
                draft_dir,
                [{"name": "毛笔行楷", "resource_id": resource_id}],
                cache_roots=[root / "empty-cache"],
            )
            material = json.loads(content_path.read_text(encoding="utf-8"))["materials"]["texts"][0]

            self.assertFalse(result["updated"])
            self.assertEqual(material["font_resource_id"], resource_id)

    def test_recognizes_font_downloaded_and_bound_by_jianying_11(self):
        with tempfile.TemporaryDirectory(prefix="jianying-bound-font-") as temporary:
            root = Path(temporary)
            draft_dir = root / "draft"
            draft_dir.mkdir()
            downloaded = root / "new-cache-layout" / "font-file"
            downloaded.parent.mkdir()
            downloaded.write_bytes(b"OTTO" + b"\0" * 2048)
            content = {
                "materials": {
                    "texts": [
                        {
                            "font_name": "毛笔行楷",
                            "font_resource_id": "new-jianying-resource-id",
                            "font_path": str(downloaded),
                            "content": json.dumps({"styles": []}),
                        }
                    ]
                }
            }
            (draft_dir / "draft_content.json").write_text(
                json.dumps(content, ensure_ascii=False),
                encoding="utf-8",
            )

            bound = find_bound_font(
                "6912033793700270606",
                name="毛笔行楷",
                draft_dir=draft_dir,
            )
            statuses = inspect_font_resources(
                [{"name": "毛笔行楷", "resource_id": "6912033793700270606"}],
                cache_roots=[root / "empty-cache"],
                draft_dir=draft_dir,
            )

            self.assertEqual(bound, downloaded.resolve())
            self.assertTrue(statuses[0]["available"])
            self.assertEqual(statuses[0]["source"], "draft_binding")

    def test_reuses_font_bound_in_another_jianying_draft(self):
        with tempfile.TemporaryDirectory(prefix="jianying-draft-library-font-") as temporary:
            draft_root = Path(temporary) / "Projects" / "com.lveditor.draft"
            source_draft = draft_root / "SOURCE"
            target_draft = draft_root / "TARGET"
            source_draft.mkdir(parents=True)
            target_draft.mkdir()
            resource_id = "6807742980271641102"
            downloaded = Path(temporary) / "downloaded-font"
            downloaded.write_bytes(b"OTTO" + b"\0" * 2048)
            (source_draft / "draft_content.json").write_text(
                json.dumps(
                    {
                        "materials": {
                            "texts": [
                                {
                                    "font_name": "Source Serif",
                                    "font_resource_id": resource_id,
                                    "font_path": str(downloaded),
                                    "content": json.dumps({"styles": []}),
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            target_content = {
                "materials": {
                    "texts": [
                        {
                            "content": json.dumps(
                                {
                                    "styles": [
                                        {"font": {"id": resource_id, "path": ""}}
                                    ],
                                    "text": "caption",
                                }
                            )
                        }
                    ]
                }
            }
            target_path = target_draft / "draft_content.json"
            target_path.write_text(json.dumps(target_content), encoding="utf-8")

            found = find_bound_font_in_draft_library(
                resource_id,
                name="Source Serif",
                draft_root=draft_root,
                exclude_dir=target_draft,
            )
            result = bind_cached_fonts(
                target_draft,
                [{"name": "Source Serif", "resource_id": resource_id}],
                draft_root=draft_root,
                cache_roots=[Path(temporary) / "empty-cache"],
            )
            updated = json.loads(target_path.read_text(encoding="utf-8"))
            style = json.loads(updated["materials"]["texts"][0]["content"])["styles"][0]

            self.assertEqual(found, downloaded.resolve())
            self.assertEqual(result["bound"], ["Source Serif"])
            self.assertEqual(style["font"]["path"], str(downloaded.resolve()))

    def test_finds_known_windows_system_font(self):
        with tempfile.TemporaryDirectory(prefix="windows-fonts-") as temporary:
            windows_dir = Path(temporary)
            installed = windows_dir / "Fonts" / "STXINGKA.TTF"
            installed.parent.mkdir()
            installed.write_bytes(b"\x00\x01\x00\x00" + b"\0" * 2048)
            with patch.dict("os.environ", {"WINDIR": str(windows_dir)}):
                found = find_system_font("6912033793700270606")

            self.assertEqual(found, installed.resolve())

    @patch("desktop_bridge.device_agent.bind_cached_fonts")
    @patch("desktop_bridge.device_agent._prepare_required_jianying_fonts_unlocked")
    @patch("desktop_bridge.device_agent.inspect_font_resources")
    @patch("desktop_bridge.device_agent.font_resources_from_import_report")
    def test_export_preloads_only_missing_fonts_before_binding_task_draft(
        self,
        extract_fonts,
        inspect_fonts,
        prepare_fonts,
        bind_fonts,
    ):
        resources = [
            {"name": "出云龙", "resource_id": "7618137748045696292"},
            {"name": "江湖体", "resource_id": "7080097079397192228"},
        ]
        extract_fonts.return_value = resources
        inspect_fonts.return_value = [
            {**resources[0], "available": True},
            {**resources[1], "available": False},
        ]
        bind_fonts.return_value = {"bound": ["出云龙", "江湖体"], "missing": []}

        result = _prepare_export_fonts(
            {"draft_dir": "C:/drafts/task"},
            Path("C:/drafts"),
            Path("C:/JianyingPro.exe"),
        )

        self.assertEqual(result, resources)
        prepared = prepare_fonts.call_args.kwargs["resources"]
        self.assertEqual([item["name"] for item in prepared], ["江湖体"])
        bind_fonts.assert_called_once_with(
            "C:/drafts/task",
            resources,
            draft_root=Path("C:/drafts"),
        )

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
