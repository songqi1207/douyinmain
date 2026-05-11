# -*- coding: utf-8 -*-
"""
Coze 书籍工作流里内联的代码节点原文（与 temp/template/每天认识一本书.txt 中节点一致）。
在 generate_book_workflow 中覆盖，避免 args.params / audio_list 为 None 时在沙箱报错。
"""

# 节点 175205：神话草稿结构 / 时间线合并
BOOK_NODE_175205_CODE = """import json
async def main(args: Args) -> Output:
    params = getattr(args, "params", None) or {}
    cover_image = params.get("pic") or ""
    bg_image = params.get("bg_pic") or cover_image
    audio_duration = int(params.get("audio_duration") or 0)
    toptitle = str(params.get("toptitle") or "")
    width = int(params.get("width") or 1920)
    height = int(params.get("height") or 1080)
    pre_time = int(params.get("pre_time") or 0)
    title_text = str(params.get("title") or "")

    imgs1 = []
    imgs2 = []
    title_captions = []
    bgm_audios = []

    title_captions.append({
        "text": title_text,
        "start": audio_duration + 1000000,
        "end": pre_time,
        "in_animation": "缩小",
        "in_animation_duration": 2000000,
    })
    topcaptions = []
    topcaptions.append({
        "text": toptitle,
        "start": audio_duration + 1000000,
        "end": pre_time,
        "in_animation": "渐显",
        "in_animation_duration": 1000000,
    })

    audios = params.get("audio_list")
    if not isinstance(audios, (list, tuple)):
        audios = []

    bgm_audios.append({
        "audio_url": "https://houht.oss-cn-shanghai.aliyuncs.com/public/booklist/book.MP3",
        "duration": 2000000,
        "start": 0,
        "end": 2000000,
    })
    bgm2_len = max(pre_time - 2000000, 0)
    bgm_audios.append({
        "audio_url": "https://houht.oss-cn-shanghai.aliyuncs.com/public/booklist/bgm2.MP3",
        "duration": bgm2_len,
        "start": 2000000,
        "end": pre_time,
    })

    imgs1.append({
        "image_url": cover_image,
        "width": 768,
        "height": 1024,
        "start": 0,
        "end": audio_duration + 1000000 + 500000,
        "transition": "中心切开",
        "transition_duration": 1000000,
    })
    imgs2.append({
        "image_url": cover_image,
        "width": 768,
        "height": 1024,
        "start": 0,
        "end": audio_duration + 1000000,
        "in_animation": "翻书",
        "in_animation_duration": audio_duration,
        "transition": "中心切开",
        "transition_duration": 1000000,
    })
    imgs2.append({
        "image_url": bg_image,
        "width": width,
        "height": height,
        "start": audio_duration + 1000000,
        "end": pre_time,
    })

    effects = []
    effects.append({
        "effect_title": "模糊",
        "end": audio_duration + 1000000,
        "start": 0,
    })

    effects2 = []
    effects2.append({
        "effect_title": "星火",
        "end": pre_time,
        "start": audio_duration + 1000000,
    })
    ret = {
        "captions": json.dumps(params.get("caption_list") or []),
        "audios": json.dumps(audios),
        "bgm_audios": json.dumps(bgm_audios),
        "imgs1": json.dumps(imgs1),
        "imgs2": json.dumps(imgs2),
        "effects": json.dumps(effects),
        "effects2": json.dumps(effects2),
        "titleCaptions": json.dumps(title_captions),
        "topcaptions": json.dumps(topcaptions),
    }
    return ret
"""

# 节点 196678：单段配音时长
BOOK_NODE_196678_CODE = """async def main(args: Args) -> Output:
    params = getattr(args, "params", None) or {}
    audios = []
    duration = float(params.get("duration") or 0)
    link = str(params.get("link") or "").strip()
    audios.append({
        "audio_url": link,
        "duration": int(duration * 1000000),
        "start": 0,
        "end": int(duration * 1000000),
    })
    ret: Output = {
        "audios": audios,
        "duration": int(duration * 1000000),
        "nextDuration": int(duration * 1000000) + 1000000,
    }
    return ret
"""
