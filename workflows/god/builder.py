#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 神明工作流：极简模式 + 网感优化

import json
import os

from config import (
    MIHE_KEY,
    MIHE_KEY_OUTPUT_DESC,
    CIGARETTE_BGM_DEFAULT,
)
from utils.template_loader import load_template
from utils.sanitize import sanitize_template_media_urls
from workflows.god.canvas import ensure_coze_temp_metadata
from workflows.god.intro_images import resolve_god_intro_images


def generate_god_workflow(
    god_name, shuliang="20", audio_url=None, god_script="", visual_style="", public_base_url=None, voice_id=""
):
    template = load_template(os.path.join("temp", "template", "\u6bcf\u5929\u8ba4\u8bc6\u4e00\u4e2a\u795e_\u4e8c\u90ce\u795e_v41_\u6700\u7ec8\u724813.txt"))
    template["source"] = {
        "workflowId": "7555696062888280107",
        "flowMode": 0,
        "spaceId": "7519871925552988214",
        "isDouyin": False,
        "host": "www.coze.cn"
    }

    audio_url = (audio_url or CIGARETTE_BGM_DEFAULT).strip()
    god_script = (god_script or "").strip()
    visual_style = (visual_style or "").strip() or (
        "\u4f20\u7edf\u53e4\u98ce\u56fd\u753b\uff1a\u5de5\u7b14\u91cd\u5f69\u6216\u6c34\u58a8\u6c61\u67d3\uff0c\u7ef8\u672c\u8bbe\u8272\uff0c\u5b8b\u4ee3\u9662\u4f53\u4eba\u7269\u7b14\u610f\uff0c"
        "\u9ad8\u53e4\u6e38\u4e1d\u63cf\u4e0e\u7559\u767d\u4e91\u6c14\uff0c\u5c71\u5e02\u697c\u9601\u82e5\u9690\u82e5\u73b0\uff0c\u795e\u8bdd\u4eba\u7269\u51a0\u5e26\u888d\u670d\uff0c"
        "\u7981\u5199\u5b9e3D\u4e0e\u897f\u753b\u5f3a\u5149\u7acb\u4f53\uff0c\u6a2a\u5c4f\u6784\u56fe"
    )

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
        if tp.get("name") in _desc_map:
            tp["description"] = _desc_map[tp["name"]]

    # ── 2. 更新 175205 的 intro_image_list ──
    intro_list_content = [{"image_url": url} for url in intro_image_urls]
    for param in nodes["175205"]["data"]["inputs"]["inputParameters"]:
        if param["name"] == "intro_image_list":
            param["input"]["value"]["content"] = intro_list_content

    # ── 3. 配音声线 ──
    _voice_id = (voice_id or "").strip() or "7620288417930297386"

    # ── 3a. 开场白缩短 ──
    if "168602" in nodes:
        for p in (nodes["168602"]["data"]["inputs"].get("inputParameters") or []):
            if p.get("name") == "String1":
                p["input"]["value"] = {"type": "literal", "content": "每天认识一个神，今天是", "rawMeta": {"type": 1}}
                break

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
            "            content_items = content_items[1:]"
        )
        if _old_split_call in old_code_196:
            old_code_196 = old_code_196.replace(_old_split_call, _new_split_call)
        n196678["data"]["inputs"]["code"] = old_code_196

    # ── 4. LLM 文案风格（修正模板中不合理的规则）──
    # 模板自带的 prompt 已有通俗化要求，但有"禁止标点"的不合理规则需要修正
    _bad_rules = [
        "- ⚠️ 禁止使用任何标点符号：不要逗号 不要句号 不要感叹号 不要问号 用空格代替停顿",
        "### 示例（注意没有标点）：\n- 「今天咱盘一位 你们绝对想不到的狠角色」\n- 「这哥们儿 三岁就能闹海 七岁就敢跟龙王叫板」\n- 「说白了 他就是神仙界的叛逆少年」\n- 「你猜最后怎么着 评论区告诉我你的答案」",
    ]
    _extra_rules = (
        "\n\n### 补充规则（最高优先级）：\n"
        "- 正常使用逗号、句号等标点，便于配音断句和字幕对齐\n"
        "- 禁止文绉绉：不要用「乃」「亦」「甚」「颇」「尤为」等书面语\n"
        "- 禁止生僻词：所有用词必须是初中生能听懂的大白话\n"
        "- 每句话都要像在跟朋友聊天，不像在念稿\n"
        "- 禁止用「今天为大家介绍的是」「今天要讲的是」「今天给大家介绍」「今天介绍」等任何形式的开头引入语，"
        "因为系统已经自动生成了「每天认识一个神，今天是XX」的开场白配音，你的第一条文案直接从正文内容开始，比如直接抛出钩子\n"
    )
    for nid in ("176492", "137312"):
        if nid not in nodes:
            continue
        llm_params = nodes[nid].get("data", {}).get("inputs", {}).get("llmParam", [])
        for p in llm_params:
            if p.get("name") == "systemPrompt":
                val = p.get("input", {}).get("value", {})
                if isinstance(val, dict) and "content" in val:
                    content = val["content"]
                    # 删除不合理的"禁止标点"规则
                    for bad in _bad_rules:
                        content = content.replace(bad, "")
                    # 追加通俗化补充规则
                    content = content.rstrip() + _extra_rules
                    val["content"] = content
                break

    # ── 8. 关键帧（模板已包含正确结构，无需修改）──

    # ── 完成 ──
    ensure_coze_temp_metadata(template)
    return sanitize_template_media_urls(template, "god", god_name)
