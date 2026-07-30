from __future__ import annotations

import json
import unittest

from desktop_bridge.draft_quality import inspect_draft_quality


def _segment(
    material_id: str,
    start: int,
    duration: int,
    *,
    x: float = 0.0,
    y: float = 0.0,
    refs: list[str] | None = None,
) -> dict:
    return {
        "material_id": material_id,
        "target_timerange": {"start": start, "duration": duration},
        "clip": {
            "alpha": 1.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": x, "y": y},
        },
        "extra_material_refs": refs or [],
    }


def _text(text_id: str, text: str = "测试字幕") -> dict:
    return {
        "id": text_id,
        "content": json.dumps(
            {"text": text, "styles": [{"size": 9}]},
            ensure_ascii=False,
        ),
    }


def _base_content() -> dict:
    return {
        "canvas_config": {"width": 1920, "height": 1080},
        "materials": {
            "texts": [_text("caption-1")],
            "material_animations": [],
            "video_effects": [],
        },
        "tracks": [
            {"name": "video_00_body", "type": "video", "segments": [_segment("video-1", 0, 5_000_000)]},
            {"name": "audio_00_bgm", "type": "audio", "segments": [_segment("bgm-1", 0, 5_000_000)]},
            {"name": "audio_02_voice", "type": "audio", "segments": [_segment("voice-1", 0, 4_500_000)]},
            {"name": "text_00_main_captions", "type": "text", "segments": [_segment("caption-1", 0, 4_500_000)]},
        ],
    }


def _codes(content: dict) -> set[str]:
    return {item["code"] for item in inspect_draft_quality(content)["issues"]}


def test_quality_check_accepts_balanced_draft() -> None:
    result = inspect_draft_quality(_base_content())

    assert result["passed"] is True
    assert result["issues"] == []


def test_quality_check_detects_caption_voice_drift() -> None:
    content = _base_content()
    content["tracks"][3]["segments"][0]["target_timerange"] = {
        "start": 800_000,
        "duration": 3_000_000,
    }

    assert "caption_voice_drift" in _codes(content)


def test_quality_check_compares_one_voice_clip_with_caption_envelope() -> None:
    content = _base_content()
    content["materials"]["texts"].append(_text("caption-2"))
    content["tracks"][3]["segments"] = [
        _segment("caption-1", 0, 2_000_000),
        _segment("caption-2", 2_000_000, 2_500_000),
    ]

    assert "caption_voice_drift" not in _codes(content)


def test_quality_check_detects_text_overlap_and_clipping() -> None:
    content = _base_content()
    content["materials"]["texts"].append(_text("caption-2"))
    content["tracks"][3]["segments"].append(
        _segment("caption-2", 4_000_000, 500_000, x=0.95)
    )

    codes = _codes(content)
    assert "text_overlap" in codes
    assert "text_out_of_bounds" in codes


def test_quality_check_detects_short_shot_and_fast_text_animation() -> None:
    content = _base_content()
    content["tracks"][0]["segments"].append(_segment("video-2", 5_000_000, 200_000))
    content["tracks"][3]["segments"][0]["extra_material_refs"] = ["animation-1"]
    content["tracks"][3]["segments"][0]["target_timerange"]["duration"] = 80_000
    content["materials"]["material_animations"].append(
        {"id": "animation-1", "animations": [{"duration": 80_000}]}
    )

    codes = _codes(content)
    assert "shot_too_short" in codes
    assert "text_display_too_fast" in codes
    assert "text_animation_too_fast" in codes


def test_quality_check_detects_parallel_bright_effects() -> None:
    content = _base_content()
    content["materials"]["video_effects"] = [
        {"id": "effect-1", "name": "闪白"},
        {"id": "effect-2", "name": "发光"},
        {"id": "effect-3", "name": "光晕"},
    ]
    content["tracks"].extend(
        [
            {"name": "effect_00_flash", "type": "effect", "segments": [_segment("effect-1", 1_000_000, 500_000)]},
            {"name": "effect_01_glow", "type": "effect", "segments": [_segment("effect-2", 1_000_000, 500_000)]},
            {"name": "effect_02_halo", "type": "effect", "segments": [_segment("effect-3", 1_000_000, 500_000)]},
        ]
    )

    assert "bright_effects_overloaded" in _codes(content)


def test_quality_check_detects_cut_ending_and_early_music() -> None:
    content = _base_content()
    content["tracks"][0]["segments"][0]["target_timerange"]["duration"] = 4_000_000
    content["tracks"][1]["segments"][0]["target_timerange"]["duration"] = 3_000_000

    codes = _codes(content)
    assert "last_voice_cut" in codes
    assert "last_caption_cut" in codes
    assert "music_ends_too_early" in codes


class DraftQualityTests(unittest.TestCase):
    def test_accepts_balanced_draft(self) -> None:
        test_quality_check_accepts_balanced_draft()

    def test_compares_one_voice_clip_with_caption_envelope(self) -> None:
        test_quality_check_compares_one_voice_clip_with_caption_envelope()

    def test_detects_caption_voice_drift(self) -> None:
        test_quality_check_detects_caption_voice_drift()

    def test_detects_text_overlap_and_clipping(self) -> None:
        test_quality_check_detects_text_overlap_and_clipping()

    def test_detects_short_shot_and_fast_text_animation(self) -> None:
        test_quality_check_detects_short_shot_and_fast_text_animation()

    def test_detects_parallel_bright_effects(self) -> None:
        test_quality_check_detects_parallel_bright_effects()

    def test_detects_cut_ending_and_early_music(self) -> None:
        test_quality_check_detects_cut_ending_and_early_music()
