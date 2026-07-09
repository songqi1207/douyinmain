#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re


_SPLIT_RE = re.compile(r"[。！？!?；;：:\n\r]+")
_TRIM_CHARS = " \t\r\n,，。！？!?；;：:\"'“”‘’、"


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
            chunk = item[start:start + max_len]
            final.append(chunk)
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

    main_shifted = [
        {"start": item["start"] + shift_us, "end": item["end"] + shift_us}
        for item in main_items
    ]
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
        pairs.append(
            {
                "effect": names[idx],
                "start": timeline_items[idx]["start"],
                "end": timeline_items[idx]["end"],
            }
        )

    return {
        "infos": json.dumps(pairs, ensure_ascii=False),
        "items": pairs,
        "count": len(pairs),
        "error": "",
    }
