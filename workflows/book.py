#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""书籍工作流生成。"""

import os

from config import MIHE_KEY, MIHE_KEY_OUTPUT_DESC, is_hotlink_protected_url
from utils.template_loader import load_template
from utils.cover import cover_url_for_coze_workflow
from utils.sanitize import sanitize_template_media_urls


def _safe_public_url(url, fallback):
    """剔除反盗链域名的 URL，换成本服务可直取的 fallback（本机 /api/cover/...）。"""
    u = (url or "").strip()
    if u and not is_hotlink_protected_url(u):
        return u
    return (fallback or "").strip()


def generate_book_workflow(book_info, public_base_url=""):
    """
    生成书籍工作流。
    public_base_url：生成 pic 字段用（Coze 需 http 图链；本地路径会转成 /api/cover/…）。
    """
    template = load_template(os.path.join("temp", "template", "书单带货1.txt"))

    title = (book_info.get("title") or "").strip()
    summary = (book_info.get("summary") or "").strip()
    content_in = (book_info.get("content") or "").strip()
    if not content_in:
        content_in = summary  # 有摘要就填，没有就留空让 LLM 自行生成

    pic_for_coze = cover_url_for_coze_workflow(book_info.get("cover", ""), public_base_url)
    cover_source_url = (book_info.get("cover_source_url") or "").strip()
    # 优先用 CDN 公网 URL（boltp/OL 等）；豆瓣 doubanio / 百度 bkimg 反盗链，Coze 侧 403，一律剔除后回退本服务 URL
    safe_source = _safe_public_url(cover_source_url, "")
    pic_for_coze_safe = safe_source if safe_source.startswith("https://") else pic_for_coze
    # 再兜一刀：pic_for_coze 理论上是自家 /api/cover 或已过滤外链，但仍防御性剔除反盗链
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
                output['value'] = MIHE_KEY
                output['defaultValue'] = MIHE_KEY
                output['description'] = MIHE_KEY_OUTPUT_DESC

    # ── 171617（大模型：书籍文案生成）──
    # 将 input 从 ref(book_name) 改为 ref(content)，让 LLM 拿到摘要作为上下文
    # 同时提升 maxTokens 以输出更长文案
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
            if isinstance(p, dict) and p.get('name') == 'systemPrompt' and content_in:
                orig = (p['input']['value'].get('content') or '')
                p['input']['value']['content'] = orig + f"\n\n## 书籍背景（参考，请勿直接照抄）\n{content_in}"

    # ── 删除图片封面节点（type='23'，但保留有 'book' 文本输入的数据节点）──
    # Coze 封面节点只支持 ByteDance CDN，外链始终报错
    # 119951 等有 book 参数的节点是书名查询节点，不能删
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

    # ── 所有依赖封面节点的文本处理节点 ──
    # String1 改为 ref(100001.tupian)，并补一条 100001→节点 的边
    _TU_TEXT_NODES = [
        '143515', '162525', '181688', '146851', '109466', '130579',
        '185147', '195811', '199046', '194563', '140765', '195939',
        '127901', '112474',
        # 152360 不在此列：它引用的是 119951（书名查询节点），应保留原始引用
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
        # 补执行链路边：文本处理节点 → 代码节点(188031)
        if (tnid, '188031') not in existing_edges:
            template['json']['edges'].append({'sourceNodeID': tnid, 'targetNodeID': '188031'})
            existing_edges.add((tnid, '188031'))

    # ── 网感优化：字幕样式 + 配音声线 + 图片铺满 + 竖屏 ──

    # 画布改竖屏 9:16（190830 create_draft）
    n_draft = nodes.get('190830')
    if n_draft:
        for p in (n_draft['data']['inputs'].get('inputParameters') or []):
            if p.get('name') == 'width':
                p['input']['value'] = {'type': 'literal', 'content': 1080, 'rawMeta': {'type': 2}}
            elif p.get('name') == 'height':
                p['input']['value'] = {'type': 'literal', 'content': 1920, 'rawMeta': {'type': 2}}

    # 生图比例改 9:16（136028 jimeng_generate_image）
    n_img = nodes.get('136028')
    if n_img:
        for p in (n_img['data']['inputs'].get('inputParameters') or []):
            if p.get('name') == 'ratio':
                p['input']['value'] = {'type': 'literal', 'content': '9:16', 'rawMeta': {'type': 1}}

    # 去掉背景图层（104801 正文背景 + 112769 画面背景 + 101422/137249 add_images + 118395/127866 keyframes）
    # 原链路: 126702 → 104801 → 112769 → 196077
    #         011558 → 101422 → 137249 → 118395 → 127866 → 131346
    # 改为:   126702 → 196077, 011558 → 131346
    _bg_node_ids = {'104801', '112769', '101422', '137249', '118395', '127866'}
    template['json']['nodes'] = [n for n in template['json']['nodes'] if n.get('id') not in _bg_node_ids]
    template['json']['edges'] = [e for e in template['json']['edges']
                                  if e.get('sourceNodeID') not in _bg_node_ids
                                  and e.get('targetNodeID') not in _bg_node_ids]
    # 补边
    template['json']['edges'].append({'sourceNodeID': '126702', 'targetNodeID': '196077'})
    template['json']['edges'].append({'sourceNodeID': '011558', 'targetNodeID': '131346'})
    # 修复 131346(add_audios) 的 draft_id 引用：从被删的 127866 改为 190830(create_draft)
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

    # 字幕样式（173584 add_captions）
    # 字幕样式（173584 add_captions）
    n_caption = nodes.get('173584')
    if n_caption:
        _book_caption_style = {
            "font_size": 10,
            "text_color": "#FFFFFF",
            "border_color": "#000000",
        }
        for p in (n_caption['data']['inputs'].get('inputParameters') or []):
            name = p.get('name')
            if name in _book_caption_style:
                p['input']['value'] = {
                    'type': 'literal',
                    'content': _book_caption_style[name],
                    'rawMeta': {'type': 1 if isinstance(_book_caption_style[name], str) else 2},
                }

    # 配音声线 + 情感（162109, 554922）
    _book_voice_id = "7620288417930297386"  # 邻家女孩2.0
    for tts_id in ['162109', '554922']:
        tts_node = nodes.get(tts_id)
        if not tts_node:
            continue
        params_list = tts_node['data']['inputs'].get('inputParameters') or []
        for p in params_list:
            if p.get('name') == 'voice_id':
                p['input']['value'] = {'type': 'literal', 'content': _book_voice_id, 'rawMeta': {'type': 1}}
        # 追加 emotion
        has_emotion = any(p.get('name') == 'emotion' for p in params_list)
        if not has_emotion:
            params_list.append({
                "name": "emotion",
                "input": {"type": "string", "value": {"type": "literal", "content": "excited", "rawMeta": {"type": 1}}},
            })
            params_list.append({
                "name": "emotion_scale",
                "input": {"type": "integer", "value": {"type": "literal", "content": 3, "rawMeta": {"type": 2}}},
            })

    # 图片铺满（所有 add_images 节点的 scale 改成 1）
    _img_nodes = ['165842', '722699', '889090', '556513', '007293', '011558']
    for img_id in _img_nodes:
        img_node = nodes.get(img_id)
        if not img_node:
            continue
        for p in (img_node['data']['inputs'].get('inputParameters') or []):
            if p.get('name') in ('scale_x', 'scale_y'):
                p['input']['value'] = {'type': 'literal', 'content': 1, 'rawMeta': {'type': 2}}

    return sanitize_template_media_urls(template, "book", book_info.get("title", ""))
