import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.jianying_drafts import _build_text_material, _resolve_text_animation, append_captions, create_draft


class JianyingTextMaterialTests(unittest.TestCase):
    def test_huawen_xingkai_uses_mihe_maobi_xingkai_resource(self):
        material = _build_text_material(
            text="正文",
            font_size=14,
            text_color="#dfd5d5",
            border_color="#000000",
            line_spacing=-3,
            alignment=1,
            font_name="华文行楷",
        )

        style = json.loads(material["content"])["styles"][0]
        self.assertEqual(material["font_name"], "毛笔行楷")
        self.assertEqual(material["font_id"], "6912033793700270606")
        self.assertEqual(style["font"]["id"], "6912033793700270606")
        self.assertEqual(style["font"]["path"], "毛笔行楷.ttf")
        self.assertEqual(len(style["strokes"]), 1)

    def test_style_text_preserves_supported_overrides(self):
        material = _build_text_material(
            text="带样式",
            font_size=14,
            text_color="#ffffff",
            border_color="",
            line_spacing=0,
            alignment=1,
            font_name="思源粗宋",
            style_text='{"bold": true, "italic": true}',
        )

        style = json.loads(material["content"])["styles"][0]
        self.assertTrue(style["bold"])
        self.assertTrue(style["italic"])

    def test_chuyunlong_uses_resource_from_god_draft(self):
        material = _build_text_material(
            text="盘古开天",
            font_size=15,
            text_color="#ffffff",
            border_color="#000000",
            line_spacing=0,
            alignment=1,
            font_name="出云龙",
        )

        style = json.loads(material["content"])["styles"][0]
        self.assertEqual(material["font_name"], "出云龙")
        self.assertEqual(material["font_id"], "7618137748045696292")
        self.assertEqual(style["font"]["id"], "7618137748045696292")

    def test_text_intro_matches_god_draft_animation_shape(self):
        animation = _resolve_text_animation("滚入", "in", 0, 112_800)

        self.assertIsNotNone(animation)
        self.assertEqual(animation["resource_id"], "7026674824537707038")
        self.assertEqual(animation["id"], "1644320")
        self.assertEqual(animation["duration"], 112_800)
        self.assertEqual(animation["material_type"], "sticker")
        self.assertEqual(animation["category_id"], "ruchang")

    def test_caption_animations_are_attached_to_text_segments(self):
        with tempfile.TemporaryDirectory() as draft_root, patch.dict(
            os.environ, {"JIANYING_DRAFT_ROOT": draft_root}
        ):
            created = create_draft(1080, 1920, "字幕动画测试")
            result = append_captions(
                created["draft_id"],
                [
                    {
                        "text": "盘古开天",
                        "start": 0,
                        "end": 1_000_000,
                        "in_animation": "滚入",
                        "in_animation_duration": 112_800,
                    },
                    {
                        "text": "女娲补天",
                        "start": 1_000_000,
                        "end": 2_000_000,
                        "in_animation": "放大",
                        "in_animation_duration": 800_000,
                    },
                ],
                font="出云龙",
            )

            draft = json.loads((Path(created["draft_dir"]) / "draft_content.json").read_text(encoding="utf-8"))
            animation_materials = draft["materials"]["material_animations"]
            text_track = next(track for track in draft["tracks"] if track["type"] == "text")

            self.assertEqual(result["warnings"], [])
            self.assertEqual(len(animation_materials), 2)
            self.assertEqual(
                [row["animations"][0]["name"] for row in animation_materials],
                ["滚入", "放大"],
            )
            self.assertEqual(
                [segment["extra_material_refs"][-1] for segment in text_track["segments"]],
                [row["id"] for row in animation_materials],
            )


if __name__ == "__main__":
    unittest.main()
