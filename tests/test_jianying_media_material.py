import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.jianying_drafts import (
    append_audios,
    append_images,
    append_videos,
    create_draft,
    extend_visual_tail_to_audio,
)


class JianyingMediaMaterialTests(unittest.TestCase):
    def test_visual_tail_does_not_extend_over_a_real_final_photo(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"JIANYING_DRAFT_ROOT": temporary}
        ):
            from PIL import Image

            first = Path(temporary) / "first.png"
            final = Path(temporary) / "final.png"
            Image.new("RGB", (16, 16), "red").save(first)
            Image.new("RGB", (16, 16), "blue").save(final)
            audio = Path(temporary) / "voice.mp3"
            audio.write_bytes(b"audio-placeholder")
            created = create_draft(1080, 1920, "book-tail-test")
            append_audios(
                created["draft_id"],
                [{"audio_url": str(audio), "start": 0, "end": 4_000_000}],
            )
            append_images(
                created["draft_id"],
                [
                    {"image_url": str(first), "start": 0, "end": 2_000_000},
                    {"image_url": str(final), "start": 2_000_000, "end": 4_000_000},
                ],
            )

            result = extend_visual_tail_to_audio(created["draft_id"])
            draft = json.loads(
                (Path(created["draft_dir"]) / "draft_content.json").read_text(encoding="utf-8")
            )
            video_segments = next(track for track in draft["tracks"] if track["type"] == "video")[
                "segments"
            ]

            self.assertEqual(result["extended_us"], 0)
            self.assertEqual(video_segments[0]["target_timerange"]["duration"], 2_000_000)
            self.assertEqual(video_segments[1]["target_timerange"]["duration"], 2_000_000)

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
