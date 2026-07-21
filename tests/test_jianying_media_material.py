import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.jianying_drafts import append_videos, create_draft


class JianyingMediaMaterialTests(unittest.TestCase):
    def test_video_url_and_visual_properties_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"JIANYING_DRAFT_ROOT": temporary}
        ):
            source = Path(temporary) / "background.mp4"
            source.write_bytes(b"draft-key-video-placeholder")
            created = create_draft(1920, 1080, "视频素材记录测试")

            result = append_videos(
                created["draft_id"],
                [
                    {
                        "video_url": str(source),
                        "start": 0,
                        "end": 2_000_000,
                        "width": 1920,
                        "height": 1080,
                        "alpha": 0.8,
                        "scale_x": 1.2,
                        "scale_y": 1.1,
                        "transform_x": -0.2,
                        "transform_y": 0.1,
                        "rotation": 12,
                        "flip_horizontal": True,
                        "in_animation": "Kira游动",
                        "in_animation_duration": 500_000,
                    }
                ],
            )

            draft = json.loads(
                (Path(created["draft_dir"]) / "draft_content.json").read_text(encoding="utf-8")
            )
            material = draft["materials"]["videos"][0]
            segment = next(track for track in draft["tracks"] if track["type"] == "video")[
                "segments"
            ][0]

            self.assertEqual(result["warnings"], [])
            self.assertEqual(material["type"], "video")
            self.assertTrue(Path(material["path"]).is_file())
            self.assertEqual(segment["clip"]["alpha"], 0.8)
            self.assertEqual(segment["clip"]["scale"], {"x": 1.2, "y": 1.1})
            self.assertEqual(segment["clip"]["transform"], {"x": -0.2, "y": 0.1})
            self.assertEqual(segment["clip"]["rotation"], 12)
            self.assertTrue(segment["clip"]["flip"]["horizontal"])
            self.assertEqual(
                draft["materials"]["material_animations"][0]["animations"][0]["name"],
                "Kira游动",
            )


if __name__ == "__main__":
    unittest.main()
