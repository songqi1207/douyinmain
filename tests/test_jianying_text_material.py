import json
import unittest

from utils.jianying_drafts import _build_text_material


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


if __name__ == "__main__":
    unittest.main()
