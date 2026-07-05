#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为神明工作流提供开场轮播图列表。

图片托管在 boltp.com CDN，每位神明对应一个固定 URL。
未登记的神明，自动生成与轮播尺寸一致的占位图（写入 static/intro_placeholder/）。
"""

import hashlib
import os
import random

GOD_IMAGE_MAP = {
    "孙悟空": "https://a1.boltp.com/2026/05/11/6a01e4247bf71.jpg",  # 暂用哪吒图，后续替换
    "二郎神": "https://a1.boltp.com/2026/05/11/6a01e41b5704f.jpg",
    "何仙姑": "https://a1.boltp.com/2026/05/11/6a01e41d8ae6a.jpg",
    "关圣帝君": "https://a1.boltp.com/2026/05/11/6a01e41fbd47c.jpg",
    "吕洞宾": "https://a1.boltp.com/2026/05/11/6a01e422022ec.jpg",
    "哪吒": "https://a1.boltp.com/2026/05/11/6a01e4247bf71.jpg",
    "城隍爷": "https://a1.boltp.com/2026/05/11/6a01e426a7c57.jpg",
    "太上老君": "https://a1.boltp.com/2026/05/11/6a01e428e5462.jpg",
    "妈祖": "https://a1.boltp.com/2026/05/11/6a01e42b27d2b.jpg",
    "嫦娥": "https://a1.boltp.com/2026/05/11/6a01e42d9d996.jpg",
    "托塔李天王": "https://a1.boltp.com/2026/05/11/6a01e4300f632.jpg",
    "文昌帝君": "https://a1.boltp.com/2026/05/11/6a01e4322d6a5.jpg",
    "月老": "https://a1.boltp.com/2026/05/11/6a01e43467ba3.jpg",
    "汉钟离": "https://a1.boltp.com/2026/05/11/6a01e436b76ea.jpg",
    "灶王爷": "https://a1.boltp.com/2026/05/11/6a01e43909c61.jpg",
    "玉皇大帝": "https://a1.boltp.com/2026/05/11/6a01e43b37e14.jpg",
    "王母娘娘": "https://a1.boltp.com/2026/05/11/6a01e43e55e1f.jpg",
    "瑶池金母": "https://a1.boltp.com/2026/05/11/6a01e441014b3.jpg",
    "真武大帝": "https://a1.boltp.com/2026/05/11/6a01e45b33205.jpg",
    "观音菩萨": "https://a1.boltp.com/2026/05/11/6a01e45d9c78a.jpg",
    "财神": "https://a1.boltp.com/2026/06/10/6a290570703ae.png",
    "铁拐李": "https://a1.boltp.com/2026/05/11/6a01e46266591.jpg",
}

# 指定神明的固定轮播图集（复刻已调优模板的视觉顺序）
# 未列入此处的神明，继续沿用 GOD_IMAGE_MAP + 随机填充逻辑
# 主神固定放在 index 9（第10张），左右汇聚效果的最终位置
GOD_INTRO_IMAGE_OVERRIDES = {
    "王母娘娘": [
        "https://a1.boltp.com/2026/05/11/6a01e42d9d996.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e41d8ae6a.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e4247bf71.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e43b37e14.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e43909c61.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e4300f632.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e45d9c78a.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e436b76ea.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e4322d6a5.jpg",
        "https://a1.boltp.com/2026/05/11/6a01e43e55e1f.jpg",
    ],
}


GOD_INTRO_CENTER_INDEX = 9  # 主神放在第10位（index 9），左右汇聚效果的最终位置

# 神明形象档案：用于强制 LLM 生图时贴合传统形象（防止哪吒画成大叔、嫦娥画成大妈等）。
# 每条用一句话锁定关键外貌：年龄段 + 服饰 + 法器 + 标志特征。
GOD_APPEARANCE_TRAITS = {
    "孙悟空": "年轻猴王形象，毛脸雷公嘴，火眼金睛，身穿锁子黄金甲，头戴凤翅紫金冠，手持金箍棒，威风凛凛",
    "二郎神": "年轻俊朗武将，额生第三只天眼，金盔银甲，手持三尖两刃刀，身旁可有哮天犬",
    "何仙姑": "年轻清丽女仙，淡彩素衣或天青色仙裙，手持荷花或笊篱，发髻簪花，气质飘逸",
    "关圣帝君": "红脸长髯凤眼蚕眉，身着绿色战袍金色铠甲，手持青龙偃月刀，威严正气",
    "吕洞宾": "中年文士道人形象，束发戴道冠，蓝白道袍，背负宝剑，腰间葫芦，儒雅清癯",
    "哪吒": "七八岁童子或少年，赤脚或穿红肚兜，肩披红色混天绫，手持火尖枪，脚踩风火轮，腰悬乾坤圈，可选三头六臂",
    "城隍爷": "中老年官吏形象，乌纱帽朝服玉带，胡须斑白，威严肃穆，手持笏板",
    "太上老君": "白发白须仙风道骨长者，道袍宽袖，手持拂尘，常骑青牛或乘云",
    "妈祖": "中年端庄女神，凤冠霞帔朱红宫装，立于海上风浪之间，可有金童玉女随侍",
    "嫦娥": "年轻仙女，长袖飘举，月白或浅蓝色广袖罗裙，怀抱玉兔，背景月宫桂树",
    "托塔李天王": "中年披甲武将，金盔金甲长须，左手托宝塔右手持戟，威武刚毅",
    "文昌帝君": "中年文官形象，朝服玉带头戴乌纱，手持笔或卷轴，端坐文气",
    "月老": "慈祥白发白须老者，红衣布袍手持红线，腰悬姻缘簿，面带笑意",
    "汉钟离": "袒胸大肚中年男仙，赤面长须，手持芭蕉扇，发髻双髻",
    "灶王爷": "中老年男神面容慈祥，红袍乌纱或道袍，手持笏板，可有侧伴灶王奶奶",
    "玉皇大帝": "帝王形象，冕旒衮冕黄色龙袍金边，长须端庄，手持玉圭，至尊威仪",
    "王母娘娘": "雍容华贵成熟女神，九凤金冠华丽宫装霞帔，手持寿桃或如意，仪态端庄",
    "瑶池金母": "端庄华贵女神，凤冠霞帔色彩华丽，与王母娘娘形象近似但更突出仙意",
    "真武大帝": "中年披发武神，玄色道袍赤足，长剑出鞘，足踏龟蛇，凛然威武",
    "观音菩萨": "慈眉善目女相菩萨，白衣雪袍宝冠璎珞，手持杨柳枝净瓶，法相庄严",
    "财神": "赵公明武财神：红脸黑须，金色战袍手持金鞭，骑黑虎，元宝堆积身旁",
    "铁拐李": "跛足蓬头老者，褴褛道袍背负葫芦，手拄铁拐杖，面相沧桑",
}
_INTRO_IMAGE_SIZE = (941, 1672)
_PLACEHOLDER_REL_DIR = "static/intro_placeholder"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PLACEHOLDER_ABS_DIR = os.path.join(_PROJECT_ROOT, *_PLACEHOLDER_REL_DIR.split("/"))
_PLACEHOLDER_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _generate_intro_placeholder(god_name, public_base_url):
    """未登记神明的占位图（同 941x1672 尺寸），返回可对外访问的 URL。

    public_base_url 缺失或 PIL 不可用时返回 None。
    """
    if not public_base_url:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    os.makedirs(_PLACEHOLDER_ABS_DIR, exist_ok=True)
    name_hash = hashlib.md5(god_name.encode("utf-8")).hexdigest()[:12]
    filename = f"{name_hash}.jpg"
    abs_path = os.path.join(_PLACEHOLDER_ABS_DIR, filename)

    if not os.path.exists(abs_path):
        img = Image.new("RGB", _INTRO_IMAGE_SIZE, (170, 38, 30))
        draw = ImageDraw.Draw(img)

        border_color = (212, 175, 90)
        for offset in range(8):
            draw.rectangle(
                [offset, offset,
                 _INTRO_IMAGE_SIZE[0] - 1 - offset,
                 _INTRO_IMAGE_SIZE[1] - 1 - offset],
                outline=border_color,
            )

        font = None
        for fp in _PLACEHOLDER_FONT_CANDIDATES:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, 220)
                    break
                except OSError:
                    continue
        if font is None:
            font = ImageFont.load_default()

        chars = list(god_name)
        if len(chars) >= 4:
            mid = len(chars) // 2
            lines = ["".join(chars[:mid]), "".join(chars[mid:])]
        else:
            lines = [god_name]

        line_widths, line_heights = [], []
        for line in lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except AttributeError:
                lw, lh = font.getsize(line)  # Pillow < 8.0
            line_widths.append(lw)
            line_heights.append(lh)
        gap = 40
        total_h = sum(line_heights) + gap * (len(lines) - 1)

        text_color = (245, 220, 130)
        y = (_INTRO_IMAGE_SIZE[1] - total_h) // 2
        for line, lw, lh in zip(lines, line_widths, line_heights):
            x = (_INTRO_IMAGE_SIZE[0] - lw) // 2
            draw.text((x, y), line, fill=text_color, font=font)
            y += lh + gap

        img.save(abs_path, "JPEG", quality=88)

    return f"{public_base_url.rstrip('/')}/{_PLACEHOLDER_REL_DIR}/{filename}"


def resolve_god_intro_images(god_name, public_base_url=None, max_images=10):
    """
    返回开场轮播图 URL 列表（10张，左右汇聚效果）。

    - 前9张：从其他神明随机选取，交替从左右飞入
    - 第10张（index 9）：主神图，最后飞入到中心
    - god 在 GOD_INTRO_IMAGE_OVERRIDES → 直接返回固定列表
    """
    override = GOD_INTRO_IMAGE_OVERRIDES.get(god_name)
    if override:
        return list(override[:max_images])

    matched_url = GOD_IMAGE_MAP.get(god_name)
    if not matched_url:
        matched_url = _generate_intro_placeholder(god_name, public_base_url)

    others = [url for name, url in GOD_IMAGE_MAP.items() if name != god_name]
    random.shuffle(others)

    # 前9张从others选取，主神放最后（index 9）
    selected = others[:max_images - 1]
    if matched_url:
        selected.append(matched_url)  # index 9

    while len(selected) < max_images:
        selected.append(selected[-1] if selected else matched_url)

    return selected[:max_images]
