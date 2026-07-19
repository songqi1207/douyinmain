import unittest

from utils.volcengine_vod_renderer import Material, VodConfig, VolcengineVodRenderer


class VolcengineVodRendererTests(unittest.TestCase):
    def setUp(self):
        self.renderer = object.__new__(VolcengineVodRenderer)
        self.renderer.config = VodConfig("ak", "sk", "test-space")
        effect = {
            "Name": "清晰",
            "Id": "effect-id",
            "FileUrl": {"UrlList": ["https://effect.example.com/clear"]},
        }
        self.renderer._effect_plan = lambda key: (  # type: ignore[method-assign]
            {"柔光": ("effect", effect)},
            [{"original": "柔光", "vod_panel": "effect", "replacement": "清晰", "exact": False}],
        )

    def test_build_edit_param_converts_microseconds_and_full_tos_sources(self):
        key = {
            "kind": "jianying_draft_key",
            "draft": {"width": 1920, "height": 1080},
            "calls": [
                {
                    "call_id": "images",
                    "tool": "add_images",
                    "params": {
                        "image_infos": [
                            {
                                "image_url": "image.png",
                                "start": 1_000_000,
                                "end": 4_000_000,
                                "transform_y": 22,
                            }
                        ]
                    },
                },
                {
                    "call_id": "captions",
                    "tool": "add_captions",
                    "params": {"captions": [{"text": "盘古", "start": 1_000_000, "end": 4_000_000}]},
                },
                {
                    "call_id": "effects",
                    "tool": "add_effects",
                    "params": {"effect_infos": [{"effect": "柔光", "start": 0, "end": 4_000_000}]},
                },
            ],
        }
        materials = {
            "image.png": Material(
                source="tos://bucket/path/image.png",
                mid="mid",
                kind="image",
                path="image.png",
                width=1920,
                height=1080,
            )
        }

        edit_param, report = self.renderer.build_edit_param(key, materials)

        image = edit_param["Track"][0][0]
        self.assertEqual(image["Source"], "tos://bucket/path/image.png")
        self.assertEqual(image["TargetTime"], [1000, 4000])
        self.assertEqual(image["Extra"][0]["PosY"], 22)
        caption = edit_param["Track"][1][0]
        self.assertEqual(caption["Text"], "盘古")
        self.assertNotIn("TextRes", caption)
        effect = edit_param["Track"][2][0]["Extra"][0]
        self.assertEqual(effect["Source"], "https://effect.example.com/clear")
        self.assertEqual(report["element_count"], 3)


if __name__ == "__main__":
    unittest.main()
