"""Static output-quality checks for imported Jianying drafts."""

from __future__ import annotations

import json
from typing import Any, Iterable


MAX_SYNC_DRIFT_US = 500_000
MIN_VISIBLE_SHOT_US = 300_000
MIN_VISIBLE_TEXT_US = 150_000
MIN_TEXT_ANIMATION_US = 100_000
MAX_MUSIC_TAIL_GAP_US = 750_000
END_CUT_TOLERANCE_US = 100_000
OVERLAP_TOLERANCE_US = 10_000

_CAPTION_MARKERS = ("main_captions", "body_captions", "subtitle", "captions", "caption")
_CAPTION_EXCLUDES = ("title", "slide", "label", "tip", "corner", "top", "focus", "frame")
_VOICE_MARKERS = ("voice", "narration", "tts", "dub", "旁白", "人声")
_MUSIC_MARKERS = ("bgm", "music", "背景音乐")
_HARD_FLASH_NAMES = ("闪白", "频闪", "爆闪", "闪烁")
_BRIGHT_EFFECT_NAMES = _HARD_FLASH_NAMES + ("发光", "光晕", "柔光", "高光", "金粉", "星光", "曝光")


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _range(segment: dict[str, Any]) -> tuple[int, int]:
    timerange = segment.get("target_timerange") or {}
    start = max(0, _integer(timerange.get("start")))
    return start, start + max(0, _integer(timerange.get("duration")))


def _track_name(track: dict[str, Any]) -> str:
    return str(track.get("name") or "").strip()


def _has_marker(value: str, markers: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in markers)


def _visible(segment: dict[str, Any]) -> bool:
    clip = segment.get("clip") or {}
    return _number(clip.get("alpha"), 1.0) > 0.01


def _segments(tracks: Iterable[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for track in tracks:
        name = _track_name(track)
        for segment in track.get("segments") or []:
            if isinstance(segment, dict):
                rows.append((name, segment))
    return rows


def _main_caption_tracks(text_tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = [
        track
        for track in text_tracks
        if _has_marker(_track_name(track), _CAPTION_MARKERS)
        and not _has_marker(_track_name(track), _CAPTION_EXCLUDES)
    ]
    if matches:
        return matches
    return text_tracks if len(text_tracks) == 1 else []


def _voice_tracks(audio_tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = [track for track in audio_tracks if _has_marker(_track_name(track), _VOICE_MARKERS)]
    if matches:
        return matches
    candidates = [
        track
        for track in audio_tracks
        if not _has_marker(_track_name(track), _MUSIC_MARKERS + ("sfx", "sound", "音效"))
    ]
    return candidates if len(candidates) == 1 else []


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _material_maps(content: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    materials = content.get("materials") or {}
    texts = {
        str(item.get("id")): item
        for item in materials.get("texts") or []
        if isinstance(item, dict) and item.get("id")
    }
    animations = {
        str(item.get("id")): item
        for item in materials.get("material_animations") or []
        if isinstance(item, dict) and item.get("id")
    }
    effects: dict[str, dict[str, Any]] = {}
    for group in ("video_effects", "effects"):
        for item in materials.get(group) or []:
            if isinstance(item, dict) and item.get("id"):
                effects[str(item.get("id"))] = item
    return texts, animations, effects


def _text_payload(material: dict[str, Any]) -> tuple[str, float]:
    raw = material.get("content")
    payload: dict[str, Any] = {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
    elif isinstance(raw, dict):
        payload = raw
    text = str(payload.get("text") or material.get("text") or "")
    styles = payload.get("styles") or []
    style = styles[0] if styles and isinstance(styles[0], dict) else {}
    return text, _number(style.get("size") or material.get("font_size"), 15.0)


def _text_units(value: str) -> int:
    return sum(1 if char.isspace() or ord(char) < 128 else 2 for char in value)


def _check_caption_sync(
    caption_rows: list[tuple[str, dict[str, Any]]],
    voice_rows: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not caption_rows and not voice_rows:
        return []
    if caption_rows and not voice_rows:
        return [_issue("voice_missing", "存在主字幕，但没有找到人声轨道")]
    if voice_rows and not caption_rows:
        return [_issue("caption_missing", "存在人声，但没有找到主字幕轨道")]

    issues: list[dict[str, Any]] = []
    ordered_captions = sorted(caption_rows, key=lambda row: _range(row[1])[0])
    ordered_voices = sorted(voice_rows, key=lambda row: _range(row[1])[0])

    # A common workflow shape is one continuous narration file plus several
    # caption segments. In that case, compare the two envelopes rather than
    # incorrectly comparing every caption with the whole narration clip.
    if len(ordered_voices) == 1 or len(ordered_captions) == 1:
        caption_track = ordered_captions[0][0]
        voice_track = ordered_voices[0][0]
        cap_start = min(_range(segment)[0] for _, segment in ordered_captions)
        cap_end = max(_range(segment)[1] for _, segment in ordered_captions)
        voice_start = min(_range(segment)[0] for _, segment in ordered_voices)
        voice_end = max(_range(segment)[1] for _, segment in ordered_voices)
        start_drift = abs(cap_start - voice_start)
        end_drift = abs(cap_end - voice_end)
        if start_drift > MAX_SYNC_DRIFT_US or end_drift > MAX_SYNC_DRIFT_US:
            issues.append(
                _issue(
                    "caption_voice_drift",
                    (
                        f"主字幕与人声总时长偏差过大"
                        f"（开头 {start_drift / 1000:.0f}ms，结尾 {end_drift / 1000:.0f}ms）"
                    ),
                    caption_track=caption_track,
                    voice_track=voice_track,
                    start_drift_us=start_drift,
                    end_drift_us=end_drift,
                )
            )
        for track_name, segment in ordered_captions:
            start, end = _range(segment)
            if not any(
                max(start, _range(voice)[0]) < min(end, _range(voice)[1])
                for _, voice in ordered_voices
            ):
                issues.append(
                    _issue(
                        "caption_voice_no_overlap",
                        f"字幕轨道“{track_name}”在 {start / 1_000_000:.2f}s 没有对应人声",
                        track=track_name,
                        start_us=start,
                    )
                )
        return issues

    pairs: list[tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]]] = []
    if len(ordered_captions) == len(ordered_voices):
        pairs = list(zip(ordered_captions, ordered_voices))
    for caption_track, caption in ordered_captions:
        cap_start, cap_end = _range(caption)
        paired_voice = next(
            (voice for cap, voice in pairs if cap[1] is caption),
            None,
        )
        if paired_voice:
            voice_track, voice = paired_voice
            voice_start, voice_end = _range(voice)
            candidates = [(max(0, min(cap_end, voice_end) - max(cap_start, voice_start)), voice_track, voice_start, voice_end)]
        else:
            # Several captions commonly split one narration clip. Their starts
            # and ends are not expected to equal the containing voice clip;
            # only time outside actual voice coverage is drift.
            intersections: list[tuple[int, int, str]] = []
            for voice_track, voice in ordered_voices:
                voice_start, voice_end = _range(voice)
                left = max(cap_start, voice_start)
                right = min(cap_end, voice_end)
                if right > left:
                    intersections.append((left, right, voice_track))
            if not intersections:
                issues.append(
                    _issue(
                        "caption_voice_no_overlap",
                        f"字幕轨道“{caption_track}”在 {cap_start / 1_000_000:.2f}s 没有对应人声",
                        track=caption_track,
                        start_us=cap_start,
                    )
                )
                continue
            merged: list[list[int]] = []
            for left, right, _ in sorted(intersections):
                if not merged or left > merged[-1][1]:
                    merged.append([left, right])
                else:
                    merged[-1][1] = max(merged[-1][1], right)
            covered_us = sum(right - left for left, right in merged)
            start_drift = max(0, merged[0][0] - cap_start)
            end_drift = max(0, cap_end - merged[-1][1])
            uncovered_us = max(0, cap_end - cap_start - covered_us)
            if (
                start_drift > MAX_SYNC_DRIFT_US
                or end_drift > MAX_SYNC_DRIFT_US
                or uncovered_us > MAX_SYNC_DRIFT_US
            ):
                voice_track = intersections[0][2]
                issues.append(
                    _issue(
                        "caption_voice_drift",
                        (
                            f"字幕“{caption_track}”超出人声“{voice_track}”覆盖范围"
                            f"（开头 {start_drift / 1000:.0f}ms，"
                            f"结尾 {end_drift / 1000:.0f}ms，"
                            f"累计无声 {uncovered_us / 1000:.0f}ms）"
                        ),
                        caption_track=caption_track,
                        voice_track=voice_track,
                        start_drift_us=start_drift,
                        end_drift_us=end_drift,
                        uncovered_us=uncovered_us,
                    )
                )
            continue
        overlap, voice_track, voice_start, voice_end = max(candidates, default=(0, "", 0, 0))
        if overlap <= 0:
            issues.append(
                _issue(
                    "caption_voice_no_overlap",
                    f"字幕轨道“{caption_track}”在 {cap_start / 1_000_000:.2f}s 没有对应人声",
                    track=caption_track,
                    start_us=cap_start,
                )
            )
            continue
        start_drift = abs(cap_start - voice_start)
        end_drift = abs(cap_end - voice_end)
        if start_drift > MAX_SYNC_DRIFT_US or end_drift > MAX_SYNC_DRIFT_US:
            issues.append(
                _issue(
                    "caption_voice_drift",
                    (
                        f"字幕“{caption_track}”与人声“{voice_track}”偏差过大"
                        f"（开头 {start_drift / 1000:.0f}ms，结尾 {end_drift / 1000:.0f}ms）"
                    ),
                    caption_track=caption_track,
                    voice_track=voice_track,
                    start_drift_us=start_drift,
                    end_drift_us=end_drift,
                )
            )
    return issues


def _check_text_layout(
    text_tracks: list[dict[str, Any]],
    texts: dict[str, dict[str, Any]],
    canvas_width: int,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for track in text_tracks:
        name = _track_name(track)
        ordered = sorted((segment for segment in track.get("segments") or [] if isinstance(segment, dict)), key=lambda item: _range(item)[0])
        for previous, current in zip(ordered, ordered[1:]):
            _, previous_end = _range(previous)
            current_start, _ = _range(current)
            if previous_end - current_start > OVERLAP_TOLERANCE_US:
                issues.append(
                    _issue(
                        "text_overlap",
                        f"字幕/文字轨道“{name}”在 {current_start / 1_000_000:.2f}s 发生重叠",
                        track=name,
                        start_us=current_start,
                    )
                )

        for segment in ordered:
            start, _ = _range(segment)
            clip = segment.get("clip") or {}
            transform = clip.get("transform") or {}
            scale = clip.get("scale") or {}
            x = _number(transform.get("x"))
            y = _number(transform.get("y"))
            scale_x = _number(scale.get("x"), 1.0)
            scale_y = _number(scale.get("y"), 1.0)
            if scale_x <= 0 or scale_y <= 0 or abs(x) > 0.90 or abs(y) > 0.90:
                issues.append(
                    _issue(
                        "text_out_of_bounds",
                        f"字幕/文字轨道“{name}”在 {start / 1_000_000:.2f}s 可能越界或被裁切",
                        track=name,
                        start_us=start,
                        x=x,
                        y=y,
                    )
                )
                continue

            material = texts.get(str(segment.get("material_id"))) or {}
            text, font_size = _text_payload(material)
            if not text.strip():
                continue
            width_factor = max(0.5, canvas_width / 1080.0)
            safe_units = max(
                10,
                int(26 * width_factor * 15.0 / max(1.0, font_size) / max(0.1, scale_x) * (1.0 - abs(x) * 0.5)),
            )
            longest_line = max((_text_units(line) for line in text.splitlines()), default=0)
            if longest_line > safe_units:
                display_text = text.replace("\n", " ")[:18]
                issues.append(
                    _issue(
                        "text_may_be_clipped",
                        f"文字“{display_text}”超过安全宽度，可能被裁切（轨道“{name}”）",
                        track=name,
                        start_us=start,
                        text_units=longest_line,
                        safe_units=safe_units,
                    )
                )
    return issues


def _check_pacing(
    video_tracks: list[dict[str, Any]],
    text_tracks: list[dict[str, Any]],
    animations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for track_name, segment in _segments(video_tracks):
        if not _visible(segment):
            continue
        start, end = _range(segment)
        duration = end - start
        if 0 < duration < MIN_VISIBLE_SHOT_US:
            issues.append(
                _issue(
                    "shot_too_short",
                    f"镜头轨道“{track_name}”在 {start / 1_000_000:.2f}s 仅 {duration / 1000:.0f}ms，低于 300ms",
                    track=track_name,
                    start_us=start,
                    duration_us=duration,
                )
            )

    short_text_tracks: set[str] = set()
    for track_name, segment in _segments(text_tracks):
        start, end = _range(segment)
        duration = end - start
        decorative_track = _has_marker(track_name, _CAPTION_EXCLUDES)
        if (
            not decorative_track
            and 0 < duration < MIN_VISIBLE_TEXT_US
            and track_name not in short_text_tracks
        ):
            short_text_tracks.add(track_name)
            issues.append(
                _issue(
                    "text_display_too_fast",
                    (
                        f"文字轨道“{track_name}”在 {start / 1_000_000:.2f}s 仅显示"
                        f" {duration / 1000:.0f}ms，低于 150ms"
                    ),
                    track=track_name,
                    start_us=start,
                    duration_us=duration,
                )
            )
        for material_ref in segment.get("extra_material_refs") or []:
            animation = animations.get(str(material_ref))
            if not animation:
                continue
            for item in animation.get("animations") or []:
                if not isinstance(item, dict):
                    continue
                duration = _integer(item.get("duration"))
                if 0 < duration < MIN_TEXT_ANIMATION_US:
                    issues.append(
                        _issue(
                            "text_animation_too_fast",
                            (
                                f"文字轨道“{track_name}”在 {start / 1_000_000:.2f}s 的"
                                f"动画仅 {duration / 1000:.0f}ms，低于 100ms"
                            ),
                            track=track_name,
                            start_us=start,
                            duration_us=duration,
                        )
                    )
    return issues


def _effect_name(material: dict[str, Any]) -> str:
    return str(
        material.get("name")
        or material.get("effect_name")
        or material.get("category_name")
        or material.get("resource_name")
        or ""
    ).strip()


def _check_bright_effects(
    effect_tracks: list[dict[str, Any]],
    effects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[tuple[int, int, str, str]] = []
    for track_name, segment in _segments(effect_tracks):
        name = _effect_name(effects.get(str(segment.get("material_id"))) or {})
        if not _has_marker(name, _BRIGHT_EFFECT_NAMES):
            continue
        start, end = _range(segment)
        if end > start:
            rows.append((start, end, name or "未命名高亮特效", track_name))

    boundaries = sorted({point for start, end, _, _ in rows for point in (start, end)})
    issues: list[dict[str, Any]] = []
    reported: set[tuple[str, ...]] = set()
    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left:
            continue
        active = [(name, track) for start, end, name, track in rows if start < right and end > left]
        hard = [(name, track) for name, track in active if _has_marker(name, _HARD_FLASH_NAMES)]
        names = tuple(sorted(name for name, _ in active))
        if (len(hard) >= 2 or len(active) >= 3) and names not in reported:
            reported.add(names)
            issues.append(
                _issue(
                    "bright_effects_overloaded",
                    f"{left / 1_000_000:.2f}s 同时叠加高亮/闪白特效：{'、'.join(names)}",
                    start_us=left,
                    end_us=right,
                    effects=list(names),
                )
            )
    return issues


def _check_ending(
    video_rows: list[tuple[str, dict[str, Any]]],
    caption_rows: list[tuple[str, dict[str, Any]]],
    voice_rows: list[tuple[str, dict[str, Any]]],
    music_rows: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    visible_video = [(name, segment) for name, segment in video_rows if _visible(segment)]
    if not visible_video:
        return []
    visual_end = max((_range(segment)[1] for _, segment in visible_video), default=0)
    voice_end = max((_range(segment)[1] for _, segment in voice_rows), default=0)
    caption_end = max((_range(segment)[1] for _, segment in caption_rows), default=0)
    music_end = max((_range(segment)[1] for _, segment in music_rows), default=0)
    issues: list[dict[str, Any]] = []

    if voice_end > visual_end + END_CUT_TOLERANCE_US:
        issues.append(
            _issue(
                "last_voice_cut",
                f"最后人声比最后画面多出 {(voice_end - visual_end) / 1000:.0f}ms，会被截断",
                visual_end_us=visual_end,
                voice_end_us=voice_end,
            )
        )
    if caption_end > visual_end + END_CUT_TOLERANCE_US:
        issues.append(
            _issue(
                "last_caption_cut",
                f"最后一句字幕比最后画面多出 {(caption_end - visual_end) / 1000:.0f}ms，会被截断",
                visual_end_us=visual_end,
                caption_end_us=caption_end,
            )
        )
    if voice_end and caption_end and abs(voice_end - caption_end) > MAX_SYNC_DRIFT_US:
        issues.append(
            _issue(
                "last_sentence_mismatch",
                f"最后一句字幕与人声结束时间相差 {abs(voice_end - caption_end) / 1000:.0f}ms",
                voice_end_us=voice_end,
                caption_end_us=caption_end,
            )
        )
    if music_end:
        if music_end > visual_end + END_CUT_TOLERANCE_US:
            issues.append(
                _issue(
                    "music_tail_cut",
                    f"音乐尾音比最后画面多出 {(music_end - visual_end) / 1000:.0f}ms，会被硬切",
                    visual_end_us=visual_end,
                    music_end_us=music_end,
                )
            )
        elif visual_end - music_end > MAX_MUSIC_TAIL_GAP_US:
            issues.append(
                _issue(
                    "music_ends_too_early",
                    f"音乐比最后画面提前 {(visual_end - music_end) / 1000:.0f}ms 结束",
                    visual_end_us=visual_end,
                    music_end_us=music_end,
                )
            )
    return issues


def inspect_draft_quality(content: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic output-quality issues for an imported draft."""

    tracks = [track for track in content.get("tracks") or [] if isinstance(track, dict)]
    text_tracks = [track for track in tracks if str(track.get("type") or "").lower() == "text"]
    audio_tracks = [track for track in tracks if str(track.get("type") or "").lower() == "audio"]
    video_tracks = [track for track in tracks if str(track.get("type") or "").lower() == "video"]
    effect_tracks = [
        track
        for track in tracks
        if str(track.get("type") or "").lower() in {"effect", "video_effect"}
        or _track_name(track).lower().startswith("effect_")
    ]
    caption_tracks = _main_caption_tracks(text_tracks)
    voice_tracks = _voice_tracks(audio_tracks)
    music_tracks = [track for track in audio_tracks if _has_marker(_track_name(track), _MUSIC_MARKERS)]
    caption_rows = _segments(caption_tracks)
    voice_rows = _segments(voice_tracks)
    video_rows = _segments(video_tracks)
    music_rows = _segments(music_tracks)
    texts, animations, effects = _material_maps(content)
    canvas = content.get("canvas_config") or {}
    canvas_width = max(1, _integer(canvas.get("width"), 1080))

    issues: list[dict[str, Any]] = []
    issues.extend(_check_caption_sync(caption_rows, voice_rows))
    issues.extend(_check_text_layout(text_tracks, texts, canvas_width))
    issues.extend(_check_pacing(video_tracks, text_tracks, animations))
    issues.extend(_check_bright_effects(effect_tracks, effects))
    issues.extend(_check_ending(video_rows, caption_rows, voice_rows, music_rows))

    return {
        "passed": not issues,
        "issues": issues,
        "thresholds": {
            "max_caption_voice_drift_ms": MAX_SYNC_DRIFT_US // 1000,
            "min_visible_shot_ms": MIN_VISIBLE_SHOT_US // 1000,
            "min_visible_text_ms": MIN_VISIBLE_TEXT_US // 1000,
            "min_text_animation_ms": MIN_TEXT_ANIMATION_US // 1000,
            "max_music_tail_gap_ms": MAX_MUSIC_TAIL_GAP_US // 1000,
            "max_parallel_bright_effects": 2,
            "max_parallel_hard_flash_effects": 1,
        },
    }
