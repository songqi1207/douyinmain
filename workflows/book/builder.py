#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""书籍工作流生成。"""

import os

from config import get_mihe_key, MIHE_KEY_OUTPUT_DESC, is_hotlink_protected_url
from utils.template_loader import load_template
from utils.cover import cover_url_for_coze_workflow
from utils.sanitize import sanitize_template_media_urls
from workflows.god.canvas import ensure_coze_temp_metadata


def _safe_public_url(url, fallback):
    """剔除反盗链域名的 URL，换成本服务可直取的 fallback（本机 /api/cover/...）。"""
    u = (url or "").strip()
    if u and not is_hotlink_protected_url(u):
        return u
    return (fallback or "").strip()


def generate_book_workflow(book_info, public_base_url="", shuliang="10", audio_url=None, book_script="", visual_style="", voice_id="", from_link=False, url=""):
    from config import BGM_DEFAULT
    template = load_template(os.path.join("temp", "template", "书单带货1.txt"))

    title = (book_info.get("title") or "").strip()
    summary = (book_info.get("summary") or "").strip()
    content_in = (book_info.get("content") or "").strip()
    if not content_in:
        content_in = summary

    audio_url = (audio_url or BGM_DEFAULT or "").strip()
    book_script = (book_script or "").strip()
    visual_style = (visual_style or "").strip() or (
        "电影级色彩分级，柔和光影，模拟胶片质感与书页纸张的温暖触感，"
        "文学意象，浅景深，自然光影，9:16竖屏构图"
    )
    voice_id = (voice_id or "").strip() or "7620288417930297386"

    try:
        scene_count = max(1, min(int(shuliang), 22))
    except (TypeError, ValueError):
        scene_count = 10
    shuliang = str(scene_count)

    title = (book_info.get("title") or "").strip()
    summary = (book_info.get("summary") or "").strip()
    content_in = (book_info.get("content") or "").strip()
    if not content_in:
        content_in = summary

    pic_for_coze = cover_url_for_coze_workflow(book_info.get("cover", ""), public_base_url)
    cover_source_url = (book_info.get("cover_source_url") or "").strip()
    safe_source = _safe_public_url(cover_source_url, "")
    pic_for_coze_safe = safe_source if safe_source.startswith("https://") else pic_for_coze
    if is_hotlink_protected_url(pic_for_coze_safe):
        pic_for_coze_safe = cover_url_for_coze_workflow(book_info.get("cover", ""), public_base_url)

    nodes = {node['id']: node for node in template['json']['nodes']}

    # ── 开始节点（100001）──
    start_node = nodes.get('100001')
    if start_node:
        outputs = start_node['data'].get('outputs', [])
        for output in outputs:
            if output['name'] == 'book_name':
                output['value'] = book_info.get('title', '')
                output['defaultValue'] = book_info.get('title', '')
            elif output['name'] == 'author':
                output['value'] = book_info.get('author', '')
                output['defaultValue'] = book_info.get('author', '')
            elif output['name'] == 'tupian':
                output['value'] = pic_for_coze_safe
                output['defaultValue'] = pic_for_coze_safe
            elif output['name'] == 'content':
                output['value'] = content_in
                output['defaultValue'] = content_in
            elif output['name'] == 'yinse':
                output['value'] = ''
                output['defaultValue'] = ''
            elif output['name'] == 'mihe_key':
                output['value'] = get_mihe_key()
                output['defaultValue'] = get_mihe_key()
                output['description'] = MIHE_KEY_OUTPUT_DESC

    # ── 171617（大模型：书籍文案生成）──
    n171617 = nodes.get('171617')
    if n171617:
        inp171 = n171617['data'].get('inputs') or {}
        for p in (inp171.get('inputParameters') or []):
            if isinstance(p, dict) and p.get('name') == 'input':
                p['input']['value'] = {
                    'type': 'ref',
                    'content': {'source': 'block-output', 'blockID': '100001', 'name': 'book_name'},
                    'rawMeta': {'type': 7},
                }
                break
        for p in (inp171.get('llmParam') or []):
            if isinstance(p, dict) and p.get('name') == 'maxTokens':
                p['input']['value'] = {'type': 'literal', 'content': 8192, 'rawMeta': {'type': 4}}
            if isinstance(p, dict) and p.get('name') == 'systemPrompt':
                orig = (p['input']['value'].get('content') or '')
                extra_context = ""
                if book_script:
                    extra_context += f"\n\n## 用户提供的解说文案（请据此整理分镜，保留核心信息）\n{book_script}"
                elif content_in:
                    extra_context += f"\n\n## 书籍背景（参考，请勿直接照抄）\n{content_in}"
                if visual_style:
                    extra_context += f"\n\n## 画面风格参考\n{visual_style}"
                extra_context += f"\n\n## 分镜数量要求\ncontentList 数量必须严格等于 {shuliang}"
                p['input']['value']['content'] = orig + extra_context

    # ── 删除图片封面节点（type='23'，但保留有 'book' 文本输入的数据节点）──
    def _is_image_fengmian(node):
        if node.get('type') != '23':
            return False
        params = (node['data'].get('inputs') or {}).get('inputParameters') or []
        names = {p['name'] for p in params if isinstance(p, dict)}
        return 'book' not in names
    fengmian_node_ids = {n['id'] for n in template['json']['nodes'] if _is_image_fengmian(n)}
    template['json']['nodes'] = [n for n in template['json']['nodes'] if not _is_image_fengmian(n)]
    template['json']['edges'] = [e for e in template['json']['edges']
                                  if e.get('sourceNodeID') not in fengmian_node_ids
                                  and e.get('targetNodeID') not in fengmian_node_ids]

    _TU_TEXT_NODES = [
        '143515', '162525', '181688', '146851', '109466', '130579',
        '185147', '195811', '199046', '194563', '140765', '195939',
        '127901', '112474',
    ]
    existing_edges = {(e.get('sourceNodeID'), e.get('targetNodeID')) for e in template['json']['edges']}
    for tnid in _TU_TEXT_NODES:
        tn = nodes.get(tnid)
        if not tn:
            continue
        params = (tn['data'].get('inputs') or {}).get('inputParameters') or []
        for param in params:
            if isinstance(param, dict) and param.get('name') == 'String1':
                param['input']['value'] = {
                    'type': 'literal',
                    'content': pic_for_coze_safe,
                    'rawMeta': {'type': 1},
                }
                param['input'].pop('assistType', None)
                break
        if ('100001', tnid) not in existing_edges:
            template['json']['edges'].append({'sourceNodeID': '100001', 'targetNodeID': tnid})
            existing_edges.add(('100001', tnid))
        if (tnid, '188031') not in existing_edges:
            template['json']['edges'].append({'sourceNodeID': tnid, 'targetNodeID': '188031'})
            existing_edges.add((tnid, '188031'))

    # ── 竖屏 9:16 ──
    n_draft = nodes.get('190830')
    if n_draft:
        for p in (n_draft['data']['inputs'].get('inputParameters') or []):
            if p.get('name') == 'width':
                p['input']['value'] = {'type': 'literal', 'content': 1080, 'rawMeta': {'type': 2}}
            elif p.get('name') == 'height':
                p['input']['value'] = {'type': 'literal', 'content': 1920, 'rawMeta': {'type': 2}}

    n_img = nodes.get('136028')
    if n_img:
        for p in (n_img['data']['inputs'].get('inputParameters') or []):
            if p.get('name') == 'ratio':
                p['input']['value'] = {'type': 'literal', 'content': '9:16', 'rawMeta': {'type': 1}}

    _bg_node_ids = {'104801', '112769', '101422', '137249', '118395', '127866'}
    template['json']['nodes'] = [n for n in template['json']['nodes'] if n.get('id') not in _bg_node_ids]
    template['json']['edges'] = [e for e in template['json']['edges']
                                  if e.get('sourceNodeID') not in _bg_node_ids
                                  and e.get('targetNodeID') not in _bg_node_ids]
    template['json']['edges'].append({'sourceNodeID': '126702', 'targetNodeID': '196077'})
    template['json']['edges'].append({'sourceNodeID': '011558', 'targetNodeID': '131346'})
    n_audios = nodes.get('131346')
    if n_audios:
        for p in (n_audios['data']['inputs'].get('inputParameters') or []):
            if p.get('name') == 'draft_id':
                p['input']['value'] = {
                    'type': 'ref',
                    'content': {'source': 'block-output', 'blockID': '190830', 'name': 'draft_id'},
                    'rawMeta': {'type': 1},
                }
                break

    # ── 字幕样式 ──
    n_caption = nodes.get('173584')
    if n_caption:
        _book_caption_style = {"font_size": 10, "text_color": "#FFFFFF", "border_color": "#000000"}
        for p in (n_caption['data']['inputs'].get('inputParameters') or []):
            name = p.get('name')
            if name in _book_caption_style:
                p['input']['value'] = {
                    'type': 'literal',
                    'content': _book_caption_style[name],
                    'rawMeta': {'type': 1 if isinstance(_book_caption_style[name], str) else 2},
                }

    # ── 配音声线 ──
    for tts_id in ['162109', '554922']:
        tts_node = nodes.get(tts_id)
        if not tts_node:
            continue
        params_list = tts_node['data']['inputs'].get('inputParameters') or []
        for p in params_list:
            if p.get('name') == 'voice_id':
                p['input']['value'] = {'type': 'literal', 'content': voice_id, 'rawMeta': {'type': 1}}
        if not any(p.get('name') == 'emotion' for p in params_list):
            params_list.append({"name": "emotion", "input": {"type": "string", "value": {"type": "literal", "content": "excited", "rawMeta": {"type": 1}}}})
            params_list.append({"name": "emotion_scale", "input": {"type": "integer", "value": {"type": "literal", "content": 3, "rawMeta": {"type": 2}}}})

    # ── 图片铺满 ──
    for img_id in ['165842', '722699', '889090', '556513', '007293', '011558']:
        img_node = nodes.get(img_id)
        if not img_node:
            continue
        for p in (img_node['data']['inputs'].get('inputParameters') or []):
            if p.get('name') in ('scale_x', 'scale_y'):
                p['input']['value'] = {'type': 'literal', 'content': 1, 'rawMeta': {'type': 2}}

    # ── from_link 模式：注入「抖音/小红书取链 → 字幕获取 → LLM 改写」管线 ──
    if from_link:
        url_value = (url or "").strip()
        start_outputs = nodes["100001"]["data"]["outputs"]
        if not any(o.get("name") == "url" for o in start_outputs):
            start_outputs.append({"name": "url", "type": "string", "required": False, "value": url_value, "defaultValue": url_value})
        else:
            for o in start_outputs:
                if o.get("name") == "url":
                    o["value"] = o["defaultValue"] = url_value
        start_triggers = nodes["100001"]["data"].setdefault("trigger_parameters", [])
        if not any(tp.get("name") == "url" for tp in start_triggers):
            start_triggers.append({"name": "url", "type": "string", "required": False, "value": url_value, "defaultValue": url_value})
        else:
            for tp in start_triggers:
                if tp.get("name") == "url":
                    tp["value"] = tp["defaultValue"] = url_value

        node_198838 = {
            "id": "198838",
            "type": "4",
            "meta": {"position": {"x": -8944.79967642455, "y": -3803.628616631093}},
            "data": {
                "nodeMeta": {"description": "抖音提取小红书提取链接集合", "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg", "title": "dou_book_main"},
                "inputs": {
                    "apiParam": [
                        {"input": {"type": "string", "value": {"content": "7512671564416958464", "type": "literal"}}, "name": "apiID"},
                        {"input": {"type": "string", "value": {"content": "dou_book_main", "type": "literal"}}, "name": "apiName"},
                        {"input": {"type": "string", "value": {"content": "7512671564416942080", "type": "literal"}}, "name": "pluginID"},
                        {"input": {"type": "string", "value": {"content": "抖音小红书提取链接", "type": "literal"}}, "name": "pluginName"},
                    ],
                    "inputParameters": [
                        {"name": "url", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "100001", "name": "url"}, "rawMeta": {"type": 1}}}},
                    ],
                    "settingOnError": {"processType": 1, "timeoutMs": 180000, "retryTimes": 0},
                },
                "outputs": [{"type": "string", "name": "response", "required": True, "description": "视频地址"}],
            },
        }
        node_1347033 = {
            "id": "1347033",
            "type": "4",
            "meta": {"position": {"x": -8944.79967642455, "y": -3647.826833423813}},
            "data": {
                "nodeMeta": {"description": "根据视频的语音来生成字幕", "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg", "title": "generate_video_captions_sync_1"},
                "inputs": {
                    "apiParam": [
                        {"input": {"type": "string", "value": {"content": "7403656762315948070", "type": "literal"}}, "name": "apiID"},
                        {"input": {"type": "string", "value": {"content": "generate_video_captions_sync", "type": "literal"}}, "name": "apiName"},
                        {"input": {"type": "string", "value": {"content": "7403656762315915302", "type": "literal"}}, "name": "pluginID"},
                        {"input": {"type": "string", "value": {"content": "字幕获取", "type": "literal"}}, "name": "pluginName"},
                    ],
                    "inputParameters": [
                        {"name": "url", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "198838", "name": "response"}, "rawMeta": {"type": 1}}}},
                    ],
                    "settingOnError": {"processType": 1, "timeoutMs": 180000, "retryTimes": 0},
                },
                "outputs": [
                    {"type": "object", "name": "data", "required": False, "schema": [
                        {"type": "string", "name": "content", "required": False},
                        {"type": "list", "name": "content_chunks", "required": False, "schema": {"type": "object", "schema": [
                            {"type": "float", "name": "end_time", "required": False},
                            {"type": "float", "name": "start_time", "required": False},
                            {"type": "string", "name": "text", "required": False},
                        ]}},
                    ]},
                    {"type": "string", "name": "msg", "required": False},
                ],
            },
        }
        existing_ids = {n["id"] for n in template["json"]["nodes"]}
        for new_node in (node_198838, node_1347033):
            if new_node["id"] not in existing_ids:
                template["json"]["nodes"].append(new_node)
                nodes[new_node["id"]] = new_node

        # 改写 171617 的 input 入参：从 100001.book_name 改为 1347033.data.content
        if n171617:
            for p in (n171617['data'].get('inputs', {}).get('inputParameters') or []):
                if p.get('name') == 'input':
                    p['input']['value'] = {
                        'type': 'ref',
                        'content': {'source': 'block-output', 'blockID': '1347033', 'name': 'data.content'},
                        'rawMeta': {'type': 1},
                    }
                    break

        edges = template["json"].setdefault("edges", [])
        existing_edge_keys = {(e.get("sourceNodeID"), e.get("targetNodeID")) for e in edges}
        for src, tgt in (("100001", "198838"), ("198838", "1347033"), ("1347033", "171617")):
            if (src, tgt) not in existing_edge_keys:
                edges.append({"sourceNodeID": src, "targetNodeID": tgt})

    ensure_coze_temp_metadata(template)
    return sanitize_template_media_urls(template, "book", book_info.get("title", ""))
