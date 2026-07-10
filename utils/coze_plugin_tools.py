#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from urllib.parse import urlparse

from utils.audio_probe import probe_audio_duration
from utils.local_media_generation import generated_local_path_from_url


_SPLIT_RE = re.compile(r"[。！？!?；;\n\r]+")
_TRIM_CHARS = " \t\r\n,，。！？!?；;\"'“”‘’《》"


def _to_number(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_timeline_items(items):
    normalized = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        start = _to_number(item.get("start"))
        end = _to_number(item.get("end"))
        if end < start:
            start, end = end, start
        normalized.append({"start": start, "end": end})
    normalized.sort(key=lambda x: (x["start"], x["end"]))
    return normalized


def split_text_segments(text, min_len=8, max_len=28):
    raw = str(text or "").strip()
    if not raw:
        return []

    raw = re.sub(r"\s+", " ", raw)
    parts = [p.strip(_TRIM_CHARS) for p in _SPLIT_RE.split(raw)]
    parts = [p for p in parts if p]
    if not parts:
        return []

    merged = []
    for part in parts:
        if not merged:
            merged.append(part)
            continue
        if len(part) < min_len or len(merged[-1]) < min_len:
            merged[-1] = f"{merged[-1]}，{part}"
        else:
            merged.append(part)

    final = []
    for item in merged:
        if len(item) <= max_len:
            final.append(item)
            continue
        start = 0
        while start < len(item):
            final.append(item[start:start + max_len])
            start += max_len
    return final


def merge_timelines(pre_timeline, main_timeline, gap_us=0, skip_us=0):
    pre_items = _normalize_timeline_items(pre_timeline)
    main_items = _normalize_timeline_items(main_timeline)
    gap_us = _to_number(gap_us)
    skip_us = _to_number(skip_us)

    pre_end = max((item["end"] for item in pre_items), default=0)
    shift_us = pre_end + gap_us - skip_us
    if shift_us < 0:
        shift_us = 0

    main_shifted = [{"start": item["start"] + shift_us, "end": item["end"] + shift_us} for item in main_items]
    all_timeline = pre_items + main_shifted
    last_end_us = max((item["end"] for item in all_timeline), default=0)

    return {
        "timelines": main_shifted,
        "main_timelines": main_shifted,
        "pre_timelines": pre_items,
        "all_timeline": all_timeline,
        "all_timelines": all_timeline,
        "all_main_timeline": main_shifted,
        "all_pre_timeline": pre_items,
        "all_complete_timeline": all_timeline,
        "last_end_us": last_end_us,
        "error": "",
    }


def build_effect_infos(effects, timelines):
    names = [str(item).strip() for item in (effects or []) if str(item).strip()]
    timeline_items = _normalize_timeline_items(timelines)
    size = min(len(names), len(timeline_items))

    pairs = []
    for idx in range(size):
        pairs.append({"effect": names[idx], "start": timeline_items[idx]["start"], "end": timeline_items[idx]["end"]})

    return {
        "infos": json.dumps(pairs, ensure_ascii=False),
        "items": pairs,
        "count": len(pairs),
        "error": "",
    }


def _parse_json_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _string_list(value):
    result = []
    for item in _parse_json_list(value):
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _audio_like_url(value):
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https", "file"} and not re.match(r"^[A-Za-z]:\\", text):
        return False
    lower = text.lower()
    return any(lower.endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"))


def _walk_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


def collect_audio_links(output_list):
    links = []
    for item in _parse_json_list(output_list):
        for candidate in _walk_values(item):
            if _audio_like_url(candidate):
                text = str(candidate).strip()
                if text not in links:
                    links.append(text)
    return {"links": links}


def build_audio_timelines(links, gap_us=0):
    urls = _string_list(links)
    gap = _to_number(gap_us)
    cursor = 0
    timelines = []
    for url in urls:
        target = str(generated_local_path_from_url(url) or url)
        duration_us = max(0, int(round(probe_audio_duration(target) * 1_000_000)))
        timelines.append({"start": cursor, "end": cursor + duration_us})
        cursor += duration_us + gap
    return {"timelines": timelines, "all_timelines": timelines}


def build_audio_infos(mp3_urls, timelines, audio_effect="", volume=None):
    urls = _string_list(mp3_urls)
    timeline_items = _normalize_timeline_items(timelines)
    size = min(len(urls), len(timeline_items))

    items = []
    for idx in range(size):
        item = {
            "audio_url": urls[idx],
            "start": timeline_items[idx]["start"],
            "end": timeline_items[idx]["end"],
            "duration": timeline_items[idx]["end"] - timeline_items[idx]["start"],
        }
        if audio_effect not in (None, ""):
            item["audio_effect"] = str(audio_effect)
        if volume not in (None, ""):
            try:
                item["volume"] = float(volume)
            except (TypeError, ValueError):
                pass
        items.append(item)

    return {"infos": json.dumps(items, ensure_ascii=False), "items": items, "count": len(items), "error": ""}


def build_caption_infos(texts, timelines, font_size=None):
    text_items = _string_list(texts)
    timeline_items = _normalize_timeline_items(timelines)
    size = min(len(text_items), len(timeline_items))

    items = []
    for idx in range(size):
        item = {"text": text_items[idx], "start": timeline_items[idx]["start"], "end": timeline_items[idx]["end"]}
        if font_size not in (None, ""):
            item["font_size"] = _to_number(font_size)
        items.append(item)

    return {"infos": json.dumps(items, ensure_ascii=False), "items": items, "count": len(items), "error": ""}


def build_image_infos(imgs, timelines, out_animation_duration=None):
    image_items = _string_list(imgs)
    timeline_items = _normalize_timeline_items(timelines)
    size = min(len(image_items), len(timeline_items))

    items = []
    for idx in range(size):
        item = {"image_url": image_items[idx], "start": timeline_items[idx]["start"], "end": timeline_items[idx]["end"]}
        if out_animation_duration not in (None, ""):
            item["out_animation_duration"] = _to_number(out_animation_duration)
        items.append(item)

    return {"infos": json.dumps(items, ensure_ascii=False), "items": items, "count": len(items), "error": ""}


def build_keyframes_infos(segment_infos, ctype, offsets, values, width=None, height=None):
    segments = _parse_json_list(segment_infos)
    offset_list = [part.strip() for part in str(offsets or "").split("|") if part.strip()]
    value_list = [part.strip() for part in str(values or "").split("|") if part.strip()]
    property_type = str(ctype or "").strip() or "KFTypePositionX"

    base = None
    if property_type == "KFTypePositionX" and width not in (None, ""):
        base = max(1.0, float(width))
    elif property_type == "KFTypePositionY" and height not in (None, ""):
        base = max(1.0, float(height))

    items = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or "").strip()
        start = _to_number(segment.get("start"))
        end = _to_number(segment.get("end"))
        duration = max(0, end - start)
        if not segment_id or duration <= 0:
            continue

        for raw_offset, raw_value in zip(offset_list, value_list):
            try:
                offset_pct = float(raw_offset)
                value_num = float(raw_value)
            except (TypeError, ValueError):
                continue
            offset_us = int(round(duration * offset_pct / 100.0))
            if base and property_type in {"KFTypePositionX", "KFTypePositionY"}:
                value_num = value_num / base
            items.append({"offset": offset_us, "property": property_type, "segment_id": segment_id, "value": value_num})

    return {"keyframes_infos": json.dumps(items, ensure_ascii=False), "items": items, "count": len(items), "error": ""}


def build_rolling_effect(duration_list, str_list):
    durations = [_to_number(item) for item in _parse_json_list(duration_list)]
    texts = _string_list(str_list)
    size = min(len(durations), len(texts))
    cursor = 0
    timelines = []
    subject_arr = []
    for idx in range(size):
        duration = max(0, durations[idx])
        subject_arr.append(texts[idx])
        timelines.append({"start": cursor, "end": cursor + duration})
        cursor += duration
    return {"all_timeline": timelines, "error": "", "subject_arr": subject_arr, "timelines": timelines}


def build_wenan_timeline_range(timelines, wenan):
    timeline_items = _normalize_timeline_items(timelines)
    texts = _string_list(wenan)
    size = min(len(timeline_items), len(texts))

    items = []
    for idx in range(size):
        items.append({"content": texts[idx], "start": timeline_items[idx]["start"], "end": timeline_items[idx]["end"]})
    return {"error": "", "wenanTimeline": items}


def align_text_to_audio(text, audio_url, max_chars_per_line=14):
    segments = split_text_segments(text, min_len=1, max_len=_to_number(max_chars_per_line, 14) or 14)
    if not segments:
        return {"texts": [], "timelines": [], "data": {"duration": 0, "audio_url": str(audio_url or "")}}

    target = str(generated_local_path_from_url(audio_url) or str(audio_url or "").strip())
    duration_us = max(0, int(round(probe_audio_duration(target) * 1_000_000)))
    weights = [max(1, len(re.sub(r"\s+", "", item))) for item in segments]
    total = sum(weights) or len(segments)

    cursor = 0
    timelines = []
    for idx, weight in enumerate(weights):
        if idx == len(weights) - 1:
            next_cursor = duration_us
        else:
            next_cursor = cursor + int(round(duration_us * weight / total))
        timelines.append({"start": cursor, "end": max(cursor, next_cursor)})
        cursor = next_cursor

    pairs = [{"text": segments[idx], "start": timelines[idx]["start"], "end": timelines[idx]["end"]} for idx in range(len(segments))]
    return {
        "texts": segments,
        "timelines": timelines,
        "data": {"audio_url": str(audio_url or "").strip(), "duration": round(duration_us / 1_000_000, 3), "segments": pairs},
    }
