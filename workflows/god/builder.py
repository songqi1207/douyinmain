#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 神明工作流：极简模式 + 网感优化

import json
import os

from config import (
    MIHE_KEY,
    MIHE_KEY_OUTPUT_DESC,
    GOD_BGM_DEFAULT,
)
from utils.template_loader import load_template
from utils.sanitize import sanitize_template_media_urls
from workflows.god.canvas import ensure_coze_temp_metadata
from workflows.god.combine_finalize import apply_canonical_combine_node_175205
from workflows.god.intro_images import GOD_APPEARANCE_TRAITS, resolve_god_intro_images
from workflows.god.prompts import REWRITE_SCRIPT_SYSTEM_PROMPT

INTRO_CARD_WIDTH = 768
INTRO_CARD_HEIGHT = 1024
INTRO_CARD_SCALE = 0.6
INTRO_FOCUS_SCALE = 0.8  # 主神图（imgs1）落定后比轮播卡片大一圈，强调"揭示"



def generate_god_workflow(
    god_name, shuliang="20", audio_url=None, god_script="", visual_style="", public_base_url=None, voice_id="",
    from_link=False, url="",
):
    template = load_template("\u6bcf\u5929\u8ba4\u8bc6\u4e00\u4e2a\u795e_\u738b\u6bcd\u5a18\u5a18_\u6a2a\u6ed1\u7248_V12.txt")
    template["source"] = {
        "workflowId": "7555696062888280107",
        "flowMode": 0,
        "spaceId": "7519871925552988214",
        "isDouyin": False,
        "host": "www.coze.cn"
    }

    audio_url = (audio_url or GOD_BGM_DEFAULT).strip()
    god_script = (god_script or "").strip()
    visual_style = (visual_style or "").strip() or (
        "传统古风国画：工笔重彩或水墨渲染，绸本设色，宋代院体人物笔意，"
        "高古游丝描与留白云气，山市楼阁若隐若现，神话人物冠带袍服，"
        "色彩丰富鲜明（金色、朱红、石青、石绿为主），背景明亮饱满，禁止大面积黑灰暗淡，"
        "画面必须铺满整个 16:9 横屏画布，**严禁挂轴/装裱/古籍/卷轴的黑色边框、黑色描边、黑色留白条**，"
        "不要画框装饰，画面四周直接到边缘，不留任何黑底或装裱痕迹，"
        "禁写实3D与西画强光立体，横屏构图"
    )

    # 强制贴合传统形象：把每位神明的关键外貌特征拼到 visual_style 前面，
    # 防止 LLM 把哪吒画成中年大叔、嫦娥画成大妈这类典型走样。
    _appearance = GOD_APPEARANCE_TRAITS.get(god_name)
    if _appearance:
        visual_style = f"【主神形象必须贴合】{god_name}：{_appearance}。\n{visual_style}"

    try:
        scene_count = max(1, min(int(shuliang), 22))
    except (TypeError, ValueError):
        scene_count = 5
    shuliang = str(scene_count)

    if not god_script:
        god_script = f"{god_name}\u7684\u8eab\u4efd\u80cc\u666f\u3001\u6210\u540d\u7ecf\u5386\u3001\u6700\u91cd\u8981\u7684\u7ecf\u5386\u3001\u8bb0\u5fc6\u70b9\u7684\u4f20\u8bf4\u3001\u8c61\u5f81\u80fd\u529b\u4e0e\u6587\u5316\u5f71\u54cd"

    nodes = {node["id"]: node for node in template["json"]["nodes"]}
    intro_image_urls = resolve_god_intro_images(god_name, public_base_url=public_base_url)

    # ── 1. 更新开始节点输出值 ──
    _value_map = {
        "zhuti": god_name,
        "audio": audio_url,
        "shuliang": shuliang,
        "mihe_key": MIHE_KEY,
        "wenan": god_script,
        "fengge": visual_style,
    }
    _desc_map = {"mihe_key": MIHE_KEY_OUTPUT_DESC}
    for out in nodes["100001"]["data"]["outputs"]:
        name = out.get("name")
        if name in _value_map:
            out["value"] = _value_map[name]
            out["defaultValue"] = _value_map[name]
        if name in _desc_map:
            out["description"] = _desc_map[name]
    for tp in nodes["100001"]["data"].get("trigger_parameters", []):
        name = tp.get("name")
        if name in _value_map:
            tp["defaultValue"] = _value_map[name]
            tp["value"] = _value_map[name]
        if name in _desc_map:
            tp["description"] = _desc_map[name]

    # ── 2. 更新 175205 的 intro_image_list ──
    intro_list_content = [{"image_url": url} for url in intro_image_urls]
    for param in nodes["175205"]["data"]["inputs"]["inputParameters"]:
        if param["name"] == "intro_image_list":
            param["input"]["value"]["content"] = intro_list_content

    # ── 2b. 轮播节奏：快滑一圈 → 中速逼近 → 慢速落定 ──
    # 16 层水平排布，步长 1400。假设映射为 image[i % 8] → layer[i]：
    # god (image index 4) 出现在 layer 4 (X=-4900) 和 layer 12 (X=+6300)。
    # 4 关键帧节奏（时间码 0|10|25|35）：
    #   phase1  (0→10) ：位移 -11200，整圈快滑
    #   phase2a (10→25)：再位移 +3700，中速逼近 god
    #   phase2b (25→35)：再位移 +1200，慢速缓入落定
    # layer 12 路径：6300 → -4900 → -1200 → 0
    _starts = [-10500, -9100, -7700, -6300, -4900, -3500, -2100, -700,
               700, 2100, 3500, 4900, 6300, 7700, 9100, 10500]
    _shift_p1 = -11200
    _shift_p2 = 4900
    _offscreen_x = -30000
    _layer_strs = []
    for _idx, s in enumerate(_starts):
        _final_x = 0 if _idx == 12 else _offscreen_x
        _layer_strs.append(f"{s}|{s + _shift_p1}|{s + _shift_p1 + _shift_p2}|{_final_x}")
    if "110647" in nodes:
        for p in nodes["110647"]["data"]["inputs"].get("inputParameters", []):
            if p.get("name") == "String":
                p["input"]["value"]["content"] = "。".join(_layer_strs)
                break

    # ── 2d. 轮播图层时间窗：主神一出现就让轮播退场 ──
    # 151678 (add_images) 没有 start/end 时插件默认整段视频时长，导致轮播图永久占屏，
    # 会和 imgs1 的主神放大叠成双层。end 取 focus_start = 2.4s。
    n151678 = nodes.get("151678")
    if n151678:
        ips = n151678["data"]["inputs"].setdefault("inputParameters", [])
        existing_names = {p.get("name") for p in ips}
        if "start" not in existing_names:
            ips.append({
                "name": "start",
                "input": {
                    "type": "integer",
                    "value": {"type": "literal", "content": 0, "rawMeta": {"type": 2}}
                }
            })
        _end_param = next((p for p in ips if p.get("name") == "end"), None)
        if _end_param:
            _end_param["input"]["value"]["content"] = 3210000
        else:
               ips.append({"name": "end", "input": {"type": "integer", "value": {"type": "literal", "content": 3210000, "rawMeta": {"type": 2}}}})

    # ── 2e. 轮播滑动音效：fatiao.mp3 在 0-1.75s 配合快滑+减速段 ──
    # 175205 模板里只有敲钟音效（主神揭示时），轮播滑动本身没有音效。
    # 在 bgm_audios.append(_bell_sfx_url) 之前注入一段滑动声。
    n175205_node = nodes.get("175205")
    if n175205_node:
        _175205_code = n175205_node["data"]["inputs"].get("code", "")
        _slide_sfx_block = (
            "    # 滑动音效：轮播快滑+减速段（0-1.75s），由 builder.py 注入\n"
            "    bgm_audios.append({\n"
            "        'audio_url': 'https://video-translate-web.oss-cn-beijing.aliyuncs.com/image/fatiao.mp3',\n"
            "        'duration': 1750000,\n"
            "        'start': 0,\n"
            "        'end': 1750000,\n"
            "    })\n"
        )
        _anchor = "    # 敲钟音效：主神出现时触发\n    bgm_audios.append({"
        if _slide_sfx_block.strip() not in _175205_code and _anchor in _175205_code:
            _175205_code = _175205_code.replace(
                _anchor, _slide_sfx_block + _anchor, 1
            )
        _175205_code = _175205_code.replace(
            "    _reveal_start = 5000000  # 轮播划到主题后停下来，主神出现\n",
            "    _reveal_start = 3000000  # 轮播划到主题后停下来，主神出现\n"
            "    first_pass_end = int(_reveal_start * 0.68)\n"
            "    second_pass_end = _reveal_start\n"
            "    # focus_start = 3.21s：imgs1 放大动画起始点（主神出现时刻）\n"
            "    focus_start = 3210000\n"
            "    focus_duration = max(int(intro_duration) - focus_start, 1)\n"
            "    zoom_start = focus_start\n",
        )
        _175205_code = _175205_code.replace(
            "    _carousel_duration = _reveal_start  # 轮播在主题出现时停止滑动\n",
            "    _carousel_duration = focus_start  # 主神一出现，轮播全部退场，避免双层叠加\n",
        )
        _175205_code = _175205_code.replace(
            "        'start': _reveal_start,\n        'end': _reveal_start + _bell_sfx_dur,\n",
            "        'start': zoom_start,\n        'end': zoom_start + _bell_sfx_dur,\n",
            1,
        )
        _175205_code = _175205_code.replace(
            "    title_captions = [{\n        'text': title,\n        'start': _reveal_start,\n",
            "    title_captions = [{\n        'text': title,\n        'start': zoom_start,\n",
            1,
        )
        _175205_code = _175205_code.replace(
            "    topcaptions = [{\n        'text': toptitle,\n        'start': 0,\n        'end': _reveal_start,\n",
            "    topcaptions = [{\n        'text': toptitle,\n        'start': 0,\n        'end': focus_start,\n",
            1,
        )
        _175205_code = _175205_code.replace(
            "    imgs1 = []\n",
            "    # imgs1 只负责在轮播停住后无缝接力，尺寸和轮播图保持一致\n"
            "    _focus_image = _intro_pool[4] if len(_intro_pool) > 4 else (cover_image or bg_image)\n"
            "    imgs1 = [{\n"
            "        'image_url': _focus_image,\n"
            f"        'width': {INTRO_CARD_WIDTH},\n"
            f"        'height': {INTRO_CARD_HEIGHT},\n"
            "        'start': focus_start,\n"
            "        'end': int(audios[0]['end']) if audios else int(intro_duration),\n"
            "        'in_animation': '放大',\n"
            "        'in_animation_duration': 600000,\n"
            "        'transform_x': 0,\n"
            "        'transform_y': 0,\n"
            "    }]\n",
            1,
        )
        # ── 2f. 揭示窗口最少 4.5s：开场配音短时强制延长 intro_duration ──
        # intro_duration = aud + 0.2s + 2s 静默；开场配音 3-4s 时窗口只剩 1-2s，主神图"一闪而过"
        # 锁定 _reveal_start(5s) 之后至少有 4.5s 揭示停留
        # 备注：原 "768→1920 cover 容器尺寸修正" 补丁锚点不匹配 V11 模板（768 实际是轮播缩略图尺寸
        #       而非揭示图），已删除，待找到揭示图层位置后再上放大
        _175205_code = _175205_code.replace(
            "    intro_duration = int(intro_duration) + 5000000\n",
            "    intro_duration = int(intro_duration) + 5000000\n"
            "    # 揭示窗口保底 4.5s（用户反馈：主神图停得太短）\n"
            "    intro_duration = max(int(intro_duration), 3000000 + 4500000)\n",
        )
        # ── 2g. 末尾黑屏修复：gap_hi 加 10s 缓冲 ──
        # pre_time 只算到最后一段配音结束，但 BGM/总轨道可能更长，导致正文段末尾出现 6-10s 黑屏。
        # 把 gap_filling 的上界扩到 pre_time + 10s，多出来的图片若视频更短会被剪映自动裁掉，无副作用。
        _175205_code = _175205_code.replace(
            "    gap_hi = int(pre_time)\n",
            "    gap_hi = int(pre_time) + 10000000  # 10s 缓冲，覆盖 BGM/总时长比 pre_time 长的情形\n",
        )
        n175205_node["data"]["inputs"]["code"] = _175205_code

    n174538 = nodes.get("174538")
    if n174538:
        for _param in n174538["data"]["inputs"].get("inputParameters", []):
            if _param.get("name") in {"scale_x", "scale_y"}:
                _param["input"]["value"] = {
                    "type": "literal",
                    "content": INTRO_FOCUS_SCALE,
                    "rawMeta": {"type": 4},
                }
        _174538_ips = n174538["data"]["inputs"].setdefault("inputParameters", [])
        _174538_end = next((p for p in _174538_ips if p.get("name") == "end"), None)
        if _174538_end:
            _174538_end["input"]["value"]["content"] = 3000000
        else:
            _174538_ips.append({"name": "end", "input": {"type": "integer", "value": {"type": "literal", "content": 3000000, "rawMeta": {"type": 2}}}})


    # ── 2c. 轮播图源（150301 base 数组）：把主神图放在 index 4（中间） ──
    # 16 层 = base 重复 2 次。god 在 base[4] → layer 4 (X=-4900) 和 layer 12 (X=+6300)。
    # phase1 后 layer 12 在 X=-4900，phase2a+phase2b=+4900 把它拉回 X=0 居中。
    n150301 = nodes.get("150301")
    if n150301:
        _carousel_imgs = list(intro_image_urls[:8])
        while len(_carousel_imgs) < 8:
            _carousel_imgs.append(_carousel_imgs[-1] if _carousel_imgs else "")
        _ts_imgs = ",\n      ".join(f'"{u}"' for u in _carousel_imgs)
        n150301["data"]["inputs"]["code"] = (
            "type Input = {};\n"
            "  type ImageOutput = {\n"
            "    outputs: string[];\n"
            "  };\n"
            "  async function main({ params }: { params: Input }): Promise<ImageOutput> {\n"
            "    const base = [\n"
            f"      {_ts_imgs}\n"
            "    ];\n"
            "    // 16张图：base 重复两遍。主神位于 base[4]，即 layer 4 / layer 12。\n"
            "    const outputs = [...base, ...base];\n"
            "    return { outputs };\n"
            "  }"
        )

    n151678 = nodes.get("151678")
    if n151678:
        for _param in n151678["data"]["inputs"].get("inputParameters", []):
            if _param.get("name") in {"scale_x", "scale_y"}:
                _param["input"]["value"] = {
                    "type": "literal",
                    "content": INTRO_CARD_SCALE,
                    "rawMeta": {"type": 4},
                }

    # ── 3. 配音声线 ──
    _voice_id = (voice_id or "").strip() or "7620288417930297386"

    # ── 3a. [removed] 开场白覆盖：保留 V5 模板原文 ──

    if "310628" in nodes:
        for p in (nodes["310628"]["data"]["inputs"].get("inputParameters") or []):
            if p.get("name") == "voice_id":
                p["input"]["value"] = {"type": "literal", "content": _voice_id, "rawMeta": {"type": 1}}
                break
    loop_node = nodes.get("135573")
    if loop_node:
        for block in (loop_node.get("blocks") or []):
            if block.get("id") == "102982":
                for p in (block["data"]["inputs"].get("inputParameters") or []):
                    if p.get("name") == "voice_id":
                        p["input"]["value"] = {"type": "literal", "content": _voice_id, "rawMeta": {"type": 1}}
                        break
                break

    # ── 3b. 修复 196678 缺失 captions/videos 输出 + 过滤空文案 + 安全取值 ──
    n196678 = nodes.get("196678")
    if n196678:
        old_code_196 = n196678["data"]["inputs"].get("code", "")
        # 修复 params['duration'] 和 params['link'] 直接访问（null 时崩溃导致所有输出为 null）
        old_code_196 = old_code_196.replace(
            "duration = params['duration']",
            "duration = float(params.get('duration') or 0)"
        )
        old_code_196 = old_code_196.replace(
            '"audio_url": params[\'link\']',
            '"audio_url": str(params.get(\'link\') or \'\')'
        )
        # 在 return ret 之前补上 captions 和 videos 空列表
        _old_ret = '"content_items": content_items,\n    }\n    return ret'
        _new_ret = (
            '"content_items": content_items,\n'
            '        "captions": [],\n'
            '        "videos": [],\n'
            '    }\n    return ret'
        )
        if _old_ret in old_code_196:
            old_code_196 = old_code_196.replace(_old_ret, _new_ret)
        # 过滤空字符串，避免 TTS 收到空文本导致 data=null → 字幕节点报错
        # 同时清理第一条文案中的重复开头语（LLM 有时不遵守 prompt 禁令）
        _old_split_call = "content_items = _split_content_list(content_list, shuliang)"
        _new_split_call = (
            "content_items = _split_content_list(content_list, shuliang)\n"
            "    content_items = [x for x in content_items if str(x or '').strip()]\n"
            "    # 清理第一条中的重复开头语\n"
            "    import re as _re\n"
            "    if content_items:\n"
            "        content_items[0] = _re.sub(r'^(今天(为大家|给大家|我们|咱们?)?(介绍|讲|说)(的是)?[，,：: ]*)', '', str(content_items[0])).strip()\n"
            "        if not content_items[0]:\n"
            "            content_items = content_items[1:]\n"
            "    # 方案 B：保留句中标点（逗号/顿号）让 TTS 朗读节奏自然+字幕对齐有据可循，只去句末标点\n"
            "    # 这样既避免空格碎字（了解 他这种），又减轻 ASR 同音错字（中间结构清晰，对齐插件不必猜）\n"
            "    def _strip_inner_punct(s):\n"
            "        s = str(s or '').strip()\n"
            "        if not s:\n"
            "            return s\n"
            "        # 只去句末标点：。！？及 ASCII !? 在末尾的\n"
            "        s = _re.sub(r'[。！？!?]+\\s*$', '', s)\n"
            "        return s.strip()\n"

            "    content_items = [_strip_inner_punct(x) for x in content_items]\n"
            "    content_items = [x for x in content_items if x]"
        )
        if _old_split_call in old_code_196:
            old_code_196 = old_code_196.replace(_old_split_call, _new_split_call)
        n196678["data"]["inputs"]["code"] = old_code_196

    # ── 4. from_link 模式：注入「抖音/小红书取链 → 字幕获取 → LLM 改写分镜」管线 ──
    # 流程：100001.url → 198838(dou_book_main) → 1347033(generate_video_captions_sync)
    #       → 137312(神话分镜 LLM, 改用 REWRITE_SCRIPT_SYSTEM_PROMPT 做 70% 改写)
    # 控制流：180385 (wenan 空判定) :false → 137312 已存在；新增 1347033 → 137312 形成 fan-in
    if from_link:
        # 4a. 100001 增加 url 输出（V11 模板原本没有），让 198838 能 ref 到
        url_value = (url or "").strip()
        start_outputs = nodes["100001"]["data"]["outputs"]
        if not any(o.get("name") == "url" for o in start_outputs):
            start_outputs.append({
                "name": "url",
                "type": "string",
                "required": False,
                "value": url_value,
                "defaultValue": url_value,
            })
        else:
            for o in start_outputs:
                if o.get("name") == "url":
                    o["value"] = url_value
                    o["defaultValue"] = url_value
        start_triggers = nodes["100001"]["data"].setdefault("trigger_parameters", [])
        if not any(tp.get("name") == "url" for tp in start_triggers):
            start_triggers.append({
                "name": "url",
                "type": "string",
                "required": False,
                "value": url_value,
                "defaultValue": url_value,
            })
        else:
            for tp in start_triggers:
                if tp.get("name") == "url":
                    tp["value"] = url_value
                    tp["defaultValue"] = url_value

        # 4b. 注入 198838（dou_book_main：抖音/小红书取链） + 1347033（字幕获取）
        # 节点 schema 来自 G236 工作流原始 JSON，只能整段照抄
        node_198838 = {
            "id": "198838",
            "type": "4",
            "meta": {"position": {"x": -8944.79967642455, "y": -3803.628616631093}},
            "data": {
                "nodeMeta": {
                    "description": "抖音提取小红书提取链接集合",
                    "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg",
                    "title": "dou_book_main",
                },
                "inputs": {
                    "apiParam": [
                        {"input": {"type": "string", "value": {"content": "7512671564416958464", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiID", "right": {}},
                        {"input": {"type": "string", "value": {"content": "dou_book_main", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiName", "right": {}},
                        {"input": {"type": "string", "value": {"content": "7512671564416942080", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginID", "right": {}},
                        {"input": {"type": "string", "value": {"content": "抖音小红书提取链接", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginName", "right": {}},
                        {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginVersion", "right": {}},
                        {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "tips", "right": {}},
                        {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "outDocLink", "right": {}},
                    ],
                    "inputParameters": [
                        {"name": "url", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "100001", "name": "url"}, "rawMeta": {"type": 1}}}},
                    ],
                    "settingOnError": {"processType": 1, "timeoutMs": 180000, "retryTimes": 0},
                },
                "outputs": [
                    {"type": "string", "name": "response", "required": True, "description": "视频地址"},
                ],
            },
        }
        node_1347033 = {
            "id": "1347033",
            "type": "4",
            "meta": {"position": {"x": -8944.79967642455, "y": -3647.826833423813}},
            "data": {
                "nodeMeta": {
                    "description": "根据视频的语音来生成字幕\n",
                    "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg",
                    "title": "generate_video_captions_sync_1",
                },
                "inputs": {
                    "apiParam": [
                        {"input": {"type": "string", "value": {"content": "7403656762315948070", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiID", "right": {}},
                        {"input": {"type": "string", "value": {"content": "generate_video_captions_sync", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiName", "right": {}},
                        {"input": {"type": "string", "value": {"content": "7403656762315915302", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginID", "right": {}},
                        {"input": {"type": "string", "value": {"content": "字幕获取", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginName", "right": {}},
                        {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginVersion", "right": {}},
                        {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "tips", "right": {}},
                        {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "outDocLink", "right": {}},
                    ],
                    "inputParameters": [
                        {"name": "url", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "198838", "name": "response"}, "rawMeta": {"type": 1}}}},
                    ],
                    "settingOnError": {"processType": 1, "timeoutMs": 180000, "retryTimes": 0},
                },
                "outputs": [
                    {
                        "type": "object",
                        "name": "data",
                        "required": False,
                        "schema": [
                            {"type": "string", "name": "content", "required": False},
                            {
                                "type": "list",
                                "name": "content_chunks",
                                "required": False,
                                "schema": {
                                    "type": "object",
                                    "schema": [
                                        {"type": "float", "name": "end_time", "required": False},
                                        {"type": "float", "name": "index", "required": False},
                                        {"type": "float", "name": "start_time", "required": False},
                                        {"type": "string", "name": "text", "required": False},
                                    ],
                                },
                            },
                        ],
                    },
                    {"type": "string", "name": "log_id", "required": False},
                    {"type": "string", "name": "msg", "required": False},
                    {"type": "float", "name": "code", "required": False},
                ],
            },
        }
        existing_ids = {n["id"] for n in template["json"]["nodes"]}
        for new_node in (node_198838, node_1347033):
            if new_node["id"] not in existing_ids:
                template["json"]["nodes"].append(new_node)
                nodes[new_node["id"]] = new_node

        # 4c. 把 137312 的 wenan 入参从 ref 100001.wenan 改到 ref 1347033.data.content
        n137312 = nodes.get("137312")
        if n137312:
            for p in (n137312["data"]["inputs"].get("inputParameters") or []):
                if p.get("name") == "wenan":
                    p["input"] = {
                        "type": "string",
                        "value": {
                            "type": "ref",
                            "content": {
                                "source": "block-output",
                                "blockID": "1347033",
                                "name": "data.content",
                            },
                            "rawMeta": {"type": 1},
                        },
                    }
                    break
            # 4d. 137312 systemPrompt → REWRITE_SCRIPT_SYSTEM_PROMPT（70% 改写 + 营销号腔调）
            for lp in (n137312["data"]["inputs"].get("llmParam") or []):
                if lp.get("name") == "systemPrompt":
                    lp["input"]["value"] = {
                        "type": "literal",
                        "content": REWRITE_SCRIPT_SYSTEM_PROMPT,
                        "rawMeta": {"type": 1},
                    }
                    break

        # 4e. 重排 edges + 拆掉 180385/176492 分支：
        # from_link 模式下不需要"用户文案 vs LLM 生成"的二选一选择器，
        # 强制走 198838→1347033→137312→168273 单一新链。
        # 必须删干净，否则：
        #   - 留 180385:false → 137312：137312 有两条无条件入边 → "并行线路互相交叉"
        #   - 只删 false 边：180385:false 端口悬空 → "port 'false' has not be connected"
        edges = template["json"].setdefault("edges", [])
        # 删除涉及 180385/176492 的全部边
        edges[:] = [
            e for e in edges
            if e.get("sourceNodeID") not in ("180385", "176492")
            and e.get("targetNodeID") not in ("180385", "176492")
        ]
        # 删除 180385/176492 节点本身（避免孤立节点报错）
        template["json"]["nodes"] = [
            n for n in template["json"]["nodes"]
            if n.get("id") not in ("180385", "176492")
        ]
        nodes.pop("180385", None)
        nodes.pop("176492", None)
        # 4e-bis. 清理 168273（变量聚合）里所有指向被删 176492 的 ref
        # 每组 mergeGroups 原本有两个 ref（176492 + 137312），删掉 176492 后保留 137312 即可
        n168273 = nodes.get("168273")
        if n168273:
            for group in n168273["data"]["inputs"].get("mergeGroups", []):
                group["variables"] = [
                    v for v in group.get("variables", [])
                    if (((v.get("value") or {}).get("content") or {}).get("blockID") != "176492")
                ]
        # 添加新链 edges：100001 → 198838 → 1347033 → 137312
        # 137312 → 168273 已存在，不动
        existing_edge_keys = {
            (e.get("sourceNodeID"), e.get("targetNodeID"), e.get("sourcePortID", ""))
            for e in edges
        }
        for src, tgt in (("100001", "198838"), ("198838", "1347033"), ("1347033", "137312")):
            if (src, tgt, "") not in existing_edge_keys:
                edges.append({"sourceNodeID": src, "targetNodeID": tgt})

    # ── 7b. [removed] 静态背景节点：V5 横滑版不使用 ──

    # ── 8. 关键帧（模板已包含正确结构，无需修改）──

    # ── 8a. [removed] 开场图层 scale 覆盖：保留 V5 模板原值 ──

    # ── 8b. [removed] 进度条节点删除 / 轮播关键帧删除：均为 v41 专属改造，V5 不需要 ──

    # ── 9. [removed] 字体/字号/字距覆盖：保留 V5 模板原样式 ──

    # ── 完成 ──
    apply_canonical_combine_node_175205(template)
    ensure_coze_temp_metadata(template)
    return sanitize_template_media_urls(template, "god", god_name)
