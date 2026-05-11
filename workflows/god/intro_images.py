#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为神明工作流提供开场轮播图列表。

图片托管在 upload.cc，每位神明对应一个固定 URL。
"""

import random

GOD_IMAGE_MAP = {
    "何仙姑": "https://upload.cc/i1/2026/05/03/ncL18R.png",
    "汉钟离": "https://upload.cc/i1/2026/05/03/cs7MqU.png",
    "月老": "https://upload.cc/i1/2026/05/03/Upxdch.png",
    "玉皇大帝": "https://upload.cc/i1/2026/05/03/KCim4P.png",
    "瑶池金母": "https://upload.cc/i1/2026/05/03/Au1RmO.png",
    "王母娘娘": "https://upload.cc/i1/2026/05/03/GSQevz.png",
    "李天王": "https://upload.cc/i1/2026/05/03/0CkbhP.png",
    "哪吒": "https://upload.cc/i1/2026/05/03/5Jex9P.png",
    "观音菩萨": "https://upload.cc/i1/2026/05/03/lo4LBD.png",
}


def resolve_god_intro_images(god_name, public_base_url=None, max_images=8):
    """
    返回开场轮播图 URL 列表。

    - 从 GOD_IMAGE_MAP 中选取图片
    - 本期主神放在列表末尾，便于横滑后「落定」到本期主神
    - 其余随机选取填满 max_images 个槽位
    """
    matched_url = GOD_IMAGE_MAP.get(god_name)
    others = [url for name, url in GOD_IMAGE_MAP.items() if name != god_name]

    random.shuffle(others)
    slots = max_images - (1 if matched_url else 0)
    selected = others[:max(slots, 0)]

    if matched_url:
        selected.append(matched_url)

    return selected
