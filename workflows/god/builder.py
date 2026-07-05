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
from workflows.god.topology_fix import fix_coze_edge_topology

INTRO_CARD_WIDTH = 768
INTRO_CARD_HEIGHT = 1024
INTRO_CARD_SCALE = 0.35  # 左右汇聚：10张图缩小显示，主神最后放大
INTRO_FOCUS_SCALE = 1.0  # 主神图节点级scale=1.0，scale_keyframes独立控制缩放动画



def _fix_coze_edge_topology(template):
    """
    \u4fee\u590d Coze \u8fb9\u62d3\u6251\u8fdd\u89c4\uff1a\u91cd\u590d\u8fb9\u3001\u5faa\u73af\u3001\u83f1\u5f62\u4ea4\u53c9\u3002

    Coze \u89c4\u5219: "\u7ebf\u8fde\u63a5\u4e0d\u5141\u8bb8\u5b58\u5728\u5e76\u884c\u7ebf\u8def\u4e92\u76f8\u4ea4\u53c9\u3001\u6210\u73af"
    - \u5e76\u884c\u7ebf\u8def\u4ea4\u53c9 = \u83f1\u5f62\u6a21\u5f0f: A\u2192C \u548c B\u2192C \u4e14\u5b58\u5728\u8def\u5f84 A\u2192...\u2192B \u6216 B\u2192...\u2192A
    - \u6210\u73af = \u5faa\u73af: \u5b58\u5728\u73af\u8def

    \u4fee\u590d\u7b56\u7565:
    1. \u53bb\u91cd
    2. \u6253\u7834\u5faa\u73af (\u79fb\u9664\u73af\u4e2d\u7684\u8fb9)
    3. \u79fb\u9664\u83f1\u5f62\u4ea4\u53c9\u4e2d\u7684\u5197\u4f59\u8fb9
    """
    edges = template["json"].setdefault("edges", [])

    # Step 1: \u53bb\u91cd
    seen = set()
    deduped = []
    for e in edges:
        key = (e.get("sourceNodeID"), e.get("targetNodeID"), e.get("sourcePortID", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    edges[:] = deduped

    # Step 2: \u6784\u5efa\u90bb\u63a5\u8868
    def build_adj(edges):
        adj = {}
        for e in edges:
            src = e.get("sourceNodeID")
            tgt = e.get("targetNodeID")
            adj.setdefault(src, set()).add(tgt)
            adj.setdefault(tgt, set())
        return adj

    adj = build_adj(edges)

    # Step 3: \u68c0\u6d4b\u5e76\u6253\u7834\u5faa\u73af
    # \u4f7f\u7528 DFS \u68c0\u6d4b back edges (\u6307\u5411\u5f53\u524d DFS \u6808\u4e2d\u8282\u70b9\u7684\u8fb9)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    back_edges = []

    def dfs_detect_cycle(u):
        color[u] = GRAY
        for v in list(adj.get(u, set())):
            if color[v] == GRAY:
                # back edge found: u -> v creates cycle
                back_edges.append((u, v))
            elif color[v] == WHITE:
                dfs_detect_cycle(v)
        color[u] = BLACK

    for node in list(adj.keys()):
        if color[node] == WHITE:
            dfs_detect_cycle(node)

    # \u79fb\u9664\u5faa\u73af\u8fb9
    # \u7b56\u7565: \u79fb\u9664\u6211\u4eec\u6dfb\u52a0\u7684\u8fb9\u6216\u73af\u4e2d\u6700\u665a\u7684\u8fb9
    # \u4f18\u5148\u79fb\u9664 bg_layer_001 -> 151678 (\u5b83\u53ea\u662f\u987a\u5e8f\u4f9d\u8d56\uff0c\u4e0d\u662f\u6570\u636e\u4f9d\u8d56)
    priority_cycle_edges = [
        ("bg_layer_001", "151678"),  # \u73af\u8fb9\uff0c151678 \u7684 draft_id \u6765\u81ea 119835\uff0c\u4e0d\u662f bg_layer_001
    ]

    for u, v in priority_cycle_edges:
        if (u, v) in back_edges:
            edges[:] = [e for e in edges if e.get("sourceNodeID") != u or e.get("targetNodeID") != v]
            back_edges = [(x, y) for x, y in back_edges if (x, y) != (u, v)]
            adj = build_adj(edges)

    # \u5982\u679c\u8fd8\u6709\u5176\u4ed6\u5faa\u73af\u8fb9\uff0c\u7ee7\u7eed\u79fb\u9664
    for u, v in back_edges:
        edges[:] = [e for e in edges if e.get("sourceNodeID") != u or e.get("targetNodeID") != v]
        adj = build_adj(edges)

    # Step 4: \u79fb\u9664\u83f1\u5f62\u4ea4\u53c9\u7684\u5197\u4f59\u8fb9
    # \u5bf9\u4e8e\u6bcf\u4e2a\u76ee\u6807\u8282\u70b9\uff0c\u68c0\u67e5\u5176\u591a\u4e2a\u5165\u8fb9\u6e90\u662f\u5426\u6709\u4f9d\u8d56\u8def\u5f84
    # \u5982\u679c A\u2192C \u548c B\u2192C \u4e14 A\u2192...\u2192B\uff0c\u5219\u79fb\u9664 A\u2192C (\u56e0\u4e3a B \u5df2\u7ecf\u4f9d\u8d56 A)

    from collections import defaultdict
    incoming = defaultdict(list)
    for e in edges:
        incoming[e.get("targetNodeID")].append(e.get("sourceNodeID"))

    # BFS \u68c0\u67e5\u8def\u5f84
    def has_path(start, end, adj):
        if start == end:
            return True
        visited = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for neighbor in adj.get(node, set()):
                if neighbor == end:
                    return True
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        return False

    edges_to_remove = []
    for target, sources in incoming.items():
        if len(sources) <= 1:
            continue
        for i, s1 in enumerate(sources):
            for s2 in sources[i+1:]:
                # \u68c0\u67e5 s1 \u5230 s2 \u6216 s2 \u5230 s1 \u662f\u5426\u6709\u8def\u5f84
                if has_path(s1, s2, adj):
                    # s1 -> ... -> s2 -> target \u5b58\u5728\uff0c\u6240\u4ee5 s1 -> target \u662f\u5197\u4f59\u7684
                    edges_to_remove.append((s1, target))
                elif has_path(s2, s1, adj):
                    edges_to_remove.append((s2, target))

    for src, tgt in edges_to_remove:
        edges[:] = [e for e in edges if e.get("sourceNodeID") != src or e.get("targetNodeID") != tgt]

    return template


def _add_batch_inputlists_as_outputs(template):
    """
    为批处理节点和循环节点添加 inputLists/input 名称作为 outputs，以通过 Coze 导入验证。

    Coze 批处理节点 (type=4) 使用自引用(如 151678.item1)访问当前迭代数据，
    Coze 循环节点 (type=21) 使用自引用(如 135573.input)访问当前迭代项，
    但 Coze 导入验证检查 outputs 列表，导致 "引用变量不存在" 错误。
    此函数将 inputLists/input 名称添加到 outputs 作为 workaround。
    """
    nodes = {n["id"]: n for n in template["json"]["nodes"]}

    # 识别批处理节点 (type=4) 和循环节点 (type=21)
    for nid, n in nodes.items():
        ntype = str(n.get("type", ""))

        if ntype == "4":
            # 批处理节点：添加 inputLists 名称
            batch_config = n.get("data", {}).get("inputs", {}).get("batch", {})
            if batch_config and batch_config.get("batchEnable"):
                input_lists = batch_config.get("inputLists", [])
                outputs = n.get("data", {}).setdefault("outputs", [])
                existing_output_names = {o.get("name") for o in outputs}

                for il in input_lists:
                    name = il.get("name")
                    if name and name not in existing_output_names:
                        inp_schema = il.get("input", {}).get("schema", {})
                        out_type = inp_schema.get("type", "string")
                        outputs.append({
                            "type": out_type,
                            "name": name,
                            "required": False,
                            "description": f"批处理迭代项 {name}",
                        })
                        existing_output_names.add(name)
                        # 嵌套 schema
                        if inp_schema.get("schema") and isinstance(inp_schema.get("schema"), list):
                            for nested_field in inp_schema.get("schema"):
                                nested_name = nested_field.get("name")
                                if nested_name:
                                    full_name = f"{name}.{nested_name}"
                                    if full_name not in existing_output_names:
                                        outputs.append({
                                            "type": nested_field.get("type", "object"),
                                            "name": full_name,
                                            "required": False,
                                            "description": f"嵌套字段 {full_name}",
                                        })
                                        existing_output_names.add(full_name)

        elif ntype in ("21", "28"):
            # 循环节点(type=21) 和 批处理节点(type=28)：
            # 添加 input (当前迭代项) 和 variableParameters 变量
            inputs = n.get("data", {}).get("inputs", {})
            outputs = n.get("data", {}).setdefault("outputs", [])
            existing_output_names = {o.get("name") for o in outputs}

            # inputParameters 中的 input (主迭代项)
            input_params = inputs.get("inputParameters", [])
            for ip in input_params:
                if ip.get("name") == "input":
                    if "input" not in existing_output_names:
                        schema = ip.get("input", {}).get("schema", {})
                        out_type = schema.get("type", "string")
                        outputs.append({
                            "type": out_type,
                            "name": "input",
                            "required": False,
                            "description": "循环当前迭代项",
                        })
                        existing_output_names.add("input")
                    # 嵌套 schema: input.infos, input.xxx 等
                    schema = ip.get("input", {}).get("schema", {})
                    if schema.get("schema") and isinstance(schema.get("schema"), list):
                        for nested_field in schema.get("schema"):
                            nested_name = nested_field.get("name")
                            if nested_name:
                                full_name = f"input.{nested_name}"
                                if full_name not in existing_output_names:
                                    outputs.append({
                                        "type": nested_field.get("type", "object"),
                                        "name": full_name,
                                        "required": False,
                                        "description": f"嵌套字段 {full_name}",
                                    })
                                    existing_output_names.add(full_name)

            # variableParameters 中声明的变量也作为 outputs
            var_params = inputs.get("variableParameters", [])
            for vp in var_params:
                vp_name = vp.get("name")
                if vp_name and vp_name not in existing_output_names:
                    schema = vp.get("input", {}).get("schema", {})
                    out_type = schema.get("type", "list")
                    outputs.append({
                        "type": out_type,
                        "name": vp_name,
                        "required": False,
                        "description": f"循环变量 {vp_name}",
                    })
                    existing_output_names.add(vp_name)

    return template


def _ensure_loop_current_item_output(template):
    """Ensure loop nodes expose the current item as an output with a self-ref.

    Coze loop bodies may reference `135573.input` from inner blocks. If the loop node
    only declares `inputParameters.input` but no matching output entry, import validation
    reports "引用变量不存在". We keep this targeted to loop nodes to avoid changing
    batch-node behavior."""
    nodes = {n["id"]: n for n in template["json"]["nodes"]}
    for nid, n in nodes.items():
        if str(n.get("type", "")) != "21":
            continue
        inputs = n.get("data", {}).get("inputs", {})
        input_params = inputs.get("inputParameters", []) or []
        loop_input = None
        for ip in input_params:
            if ip.get("name") == "input":
                loop_input = ip
                break
        if not loop_input:
            continue
        outputs = n.get("data", {}).setdefault("outputs", [])
        if any(isinstance(o, dict) and o.get("name") == "input" for o in outputs):
            continue
        input_def = loop_input.get("input", {}) or {}
        input_type = input_def.get("type", "list")
        raw_type = 99 if input_type == "list" else 1
        outputs.append({
            "type": input_type,
            "name": "input",
            "schema": input_def.get("schema", {"type": "string"}),
            "required": False,
            "description": "循环当前迭代项",
            "input": {
                "type": input_type,
                "value": {
                    "type": "ref",
                    "content": {
                        "source": "block-output",
                        "blockID": nid,
                        "name": "input",
                    },
                    "rawMeta": {"type": raw_type},
                },
            },
        })
    return template


def _ensure_output_fields(node, fields):
    """Add missing output names required by Coze import validation."""
    if not node:
        return
    outputs = node.setdefault("data", {}).setdefault("outputs", [])
    existing = {o.get("name") for o in outputs if isinstance(o, dict)}
    for name, out_type in fields:
        if name in existing:
            continue
        outputs.append({
            "name": name,
            "type": out_type,
            "required": False,
        })
        existing.add(name)


def _set_outputs(node, outputs):
    """Update node outputs while preserving each entry's `input.value.content`.

    Loop/batch nodes in V12 declare outputs with `input.value.content` self-refs pointing at
    the internal block producing each value per-iteration. Coze needs those refs to wire
    outer-graph edges; replacing outputs with plain schema strips them and Coze aborts
    outer-edge rendering. Merge instead: caller controls schema, template keeps input."""
    if not node:
        return
    existing = node.setdefault("data", {}).get("outputs") or []
    existing_by_name = {o.get("name"): o for o in existing if isinstance(o, dict)}
    merged = []
    for new_out in outputs:
        prior = existing_by_name.get(new_out.get("name"))
        if prior and "input" in prior:
            entry = dict(new_out)
            entry["input"] = prior["input"]
            merged.append(entry)
        else:
            merged.append(new_out)
    node["data"]["outputs"] = merged


def generate_god_workflow(
    god_name, shuliang="20", audio_url=None, god_script="", visual_style="", public_base_url=None, voice_id="",
    yinse="", from_link=False, url="",
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
        "yinse": yinse,
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

    # ── 1b. 动态添加 yinse 到 outputs/trigger_parameters（如果模板中没有）──
    start_outputs = nodes["100001"]["data"]["outputs"]
    if not any(o.get("name") == "yinse" for o in start_outputs):
        start_outputs.append({
            "type": "string",
            "name": "yinse",
            "required": False,
            "description": "配音音色（assistType 12 对应的音色标识）",
            "defaultValue": yinse,
            "value": yinse,
        })
    start_triggers = nodes["100001"]["data"].setdefault("trigger_parameters", [])
    if not any(tp.get("name") == "yinse" for tp in start_triggers):
        start_triggers.append({
            "type": "string",
            "name": "yinse",
            "required": False,
            "description": "配音音色（assistType 12 对应的音色标识）",
            "defaultValue": yinse,
            "value": yinse,
        })

    # ── 2. 更新 175205 的 intro_image_list ──
    intro_list_content = [{"image_url": url} for url in intro_image_urls]
    for param in nodes["175205"]["data"]["inputs"]["inputParameters"]:
        if param["name"] == "intro_image_list":
            param["input"]["value"]["content"] = intro_list_content

    # ── 2b. [removed] 110647 位置字符串已在 2d-11 统一设置 ──

    # ── 2c. 轮播图层时间窗：四面八方汇聚4.5s后退场 ──
    # 151678 (add_images) 没有 start/end 时插件默认整段视频时长。
    # 四面八方汇聚4.5s，轮播退场，主神放大开始。
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
            _end_param["input"]["value"]["content"] = 4500000  # 4.5s汇聚结束
        else:
               ips.append({"name": "end", "input": {"type": "integer", "value": {"type": "literal", "content": 4500000, "rawMeta": {"type": 2}}}})

    # ── 2e. 音效 + 时间参数调整 ──
    # 四面八方汇聚音效：飞入段0-3s，钟声在3.0s（主神飞入时）
    # 时间线：飞入(0-3s) → 主神飞入+钟声(3.0s) → 放大占屏(3.3-4.5s) → 正文(4.5s+)
    n175205_node = nodes.get("175205")
    if n175205_node:
        _175205_code = n175205_node["data"]["inputs"].get("code", "")
        _converge_sfx_block = (
            "    # 汇聚音效：四面八方飞入段（0-3s）\n"
            "    bgm_audios.append({\n"
            "        'audio_url': 'https://video-translate-web.oss-cn-beijing.aliyuncs.com/image/fatiao.mp3',\n"
            "        'duration': 3000000,\n"
            "        'start': 0,\n"
            "        'end': 3000000,\n"
            "    })\n"
        )
        _anchor = "    # 敲钟音效：主神出现时触发\n    bgm_audios.append({"
        if _converge_sfx_block.strip() not in _175205_code and _anchor in _175205_code:
            _175205_code = _175205_code.replace(
                _anchor, _converge_sfx_block + _anchor, 1
            )
        _175205_code = _175205_code.replace(
            "    _reveal_start = 5000000  # 轮播划到主题后停下来，主神出现\n",
            "    _reveal_start = 3000000  # 主神飞入时刻(3.0s)\n"
            "    focus_start = 3300000  # 3.3s，主神到中心后开始放大\n"
            "    focus_duration = max(int(intro_duration) - focus_start, 1)\n"
            "    zoom_start = focus_start\n",
        )
        _175205_code = _175205_code.replace(
            "    _carousel_duration = _reveal_start  # 轮播在主题出现时停止滑动\n",
            "    _carousel_duration = 4500000  # 四面八方汇聚4.5s后全部退场\n",
        )
        _175205_code = _175205_code.replace(
            "        'start': _reveal_start,\n        'end': _reveal_start + _bell_sfx_dur,\n",
            "        'start': 3000000,\n        'end': 3000000 + _bell_sfx_dur,\n",
            1,
        )
        _175205_code = _175205_code.replace(
            "    title_captions = [{\n        'text': title,\n        'start': _reveal_start,\n",
            "    title_captions = [{\n        'text': title,\n        'start': zoom_start,\n",
            1,
        )
        _175205_code = _175205_code.replace(
            "    topcaptions = [{\n        'text': toptitle,\n        'start': 0,\n        'end': _reveal_start,\n",
            "    topcaptions = [{\n        'text': toptitle,\n        'start': 0,\n        'end': 3000000,\n",
            1,
        )
        # ── 2g. imgs1 四面八方扑克牌堆叠效果 ──
        # 10张图从四个方向飞入，汇聚到中心，像扑克牌堆叠
        # 主神(index 9)最后飞入，然后放大占屏
        _start_positions_xy = [
            (-1500, -2000),   # 0: 左上角
            (1500, -2000),    # 1: 右上角
            (-1500, 2000),    # 2: 左下角
            (1500, 2000),     # 3: 右下角
            (-2000, -2500),   # 4: 左上角更远
            (2000, -2500),    # 5: 右上角更远
            (-2000, 2500),    # 6: 左下角更远
            (2000, 2500),     # 7: 右下角更远
            (-1800, -2200),   # 8: 左上角
            (-3000, -3000),   # 9: 主神从左上角远处飞入
        ]
        _entry_times = [0, 300000, 600000, 900000, 1200000, 1500000, 1800000, 2100000, 2400000, 3000000]
        _god_index = 9  # 主神在最后
        _img_scale = 0.35
        _god_visible_end = 4500000  # 4.5s后主神淡出

        # 修复：替换目标需要匹配模板中的实际代码
        # 注意：timing replacement 已经把 _carousel_duration = _reveal_start 改成 4500000
        # 所以这里的目标要匹配已修改后的代码
        #
        # 架构说明：
        # - Carousel 管线 (150301 → 151678 → 110647 → 111477): 处理前9张图的四角飞入动画
        # - imgs1 (175205 → 174538): 只处理主神(index 9)的放大展示
        _175205_code = _175205_code.replace(
            "    # imgs1 保留为空（主神通过轮播展示）\n"
            "    imgs1 = []\n"
            "\n"
            "    # carousel_imgs: 16张图（8张重复两遍），每张有不同的 transform_x 起始位置\n"
            "    # 通过关键帧让它们同时横向滑动\n"
            "    _double_pool = (_intro_pool + _intro_pool)[:16]\n"
            "    _carousel_duration = 4500000  # 四面八方汇聚4.5s后全部退场\n"
            "    carousel_imgs = []\n"
            "    for _ci, _curl in enumerate(_double_pool):\n"
            "        _x_pos = -7500 + _ci * 1000  # 间距1000\n"
            "        carousel_imgs.append({\n"
            "            'image_url': _curl,\n"
            "            'width': 768,\n"
            "            'height': 1024,\n"
            "            'start': 0,\n"
            "            'end': _carousel_duration,\n"
            "            'transform_x': _x_pos,\n"
            "        })",
            "    # -- imgs1: 主神放大展示（carousel 管线处理前9张四角飞入）--\n"
            "    # 前9张图由 carousel 管线渲染 (150301 → 151678 → 110647 → 111477)\n"
            "    # 110647 已设置四角位置字符串，处理四角飞入关键帧动画\n"
            "    # imgs1 只处理主神(index 9)：放大展示后淡出\n"
            "    carousel_imgs = []  # carousel 逻辑由 150301/110647 管线处理\n"
            "    imgs1 = []\n"
            "    _god_img_url = _intro_pool[9] if len(_intro_pool) > 9 else (_intro_pool[-1] if _intro_pool else '')\n"
            "    if _god_img_url:\n"
            "        imgs1.append({\n"
            "            'image_url': _god_img_url,\n"
            "            'width': 941,\n"
            "            'height': 1672,\n"
            "            'start': 3000000,  # 3.0s 主神飞入时刻\n"
            "            'end': 4500000,    # 4.5s 主神淡出，正文开始\n"
            "            'transform_x': 0,  # 居中\n"
            "            'transform_y': 0,\n"
            "            'scale_x': 0.35,\n"
            "            'scale_y': 0.35,\n"
            "            'in_animation': '放大',  # 放大入场\n"
            "            'in_animation_duration': 300000,\n"
            "            'out_animation': '淡出',  # 淡出退场\n"
            "            'out_animation_duration': 500000,\n"
            "        })\n"
            "    # carousel 不再在此处构建\n"
            "    _double_pool = []\n"
            "    _carousel_duration = 4500000",
            1,
        )
        # ── 2h. 关键段落延长：动态调整分镜时长 ──
        # 根据叙事结构：第3-5段（高潮/成王故事）用4s，最后2段（总结互动）用2s，其他用3s
        _175205_code = _175205_code.replace(
            "        slot_us = 3000000\n        _scene_anim_idx = 0\n\n        for audio_obj in scene_audios:\n",
            "        slot_us = 3000000\n"
            "        _scene_anim_idx = 0\n"
            "        _scene_slot_idx = 0  # 分镜位置计数器\n"
            "        _total_scene_slots = len(scene_audios)  # 总分镜段数\n\n"
            "        for audio_obj in scene_audios:\n",
        )
        # 在循环内根据位置动态调整slot_us
        # 注意：effects2 在模板后半段才定义（body_specs区域），
        # 所以这里不能直接 effects2.append，改为用 _pending_effects 收集，
        # 最后在 effects2 = [] 之后统一追加。
        _175205_code = _175205_code.replace(
            "            t = segment_start\n            while t < segment_end:\n                chunk_end = min(segment_end, t + slot_us)\n",
            "            t = segment_start\n"
            "            # 动态分镜时长：关键段落延长\n"
            "            if _scene_slot_idx in (2, 3, 4):  # 第3-5段是重点故事\n"
            "                slot_us = 4000000  # 4s\n"
            "            elif _scene_slot_idx >= _total_scene_slots - 2:  # 最后2段是总结互动\n"
            "                slot_us = 2000000  # 2s\n"
            "            else:\n"
            "                slot_us = 3000000  # 3s\n"
            "            # ── 情绪匹配：根据叙事段落选择镜头语言 ──\n"
            "            # 叙事结构(来自prompts.py): 1钩子→2起源→3高潮→4性格→5能力→6总结\n"
            "            _emotion_anim_map = {\n"
            "                0: ('渐显', {'scale': 1.4, 'x': 0, 'y': 0}, '暗角'),  # 钩子(悬念)\n"
            "                1: ('左摇', {'scale': 1.5, 'x': -150, 'y': 0}, '颗粒'),  # 起源(历史感)\n"
            "                2: ('拉远', {'scale': 1.8, 'x': 0, 'y': 0}, '星火'),  # 高潮战斗(宏大)\n"
            "                3: ('推近', {'scale': 1.2, 'x': 0, 'y': 0}, '闪白'),  # 高潮战斗(冲击)\n"
            "                4: ('右摇', {'scale': 1.5, 'x': 150, 'y': 0}, '梦幻'),  # 性格萌点(轻松)\n"
            "                5: ('缩小', {'scale': 1.6, 'x': 0, 'y': 0}, '金粉'),  # 能力职能(庄重)\n"
            "                6: ('渐显', {'scale': 1.5, 'x': 0, 'y': 0}, '柔光'),  # 总结(温情)\n"
            "            }\n"
            "            # 默认映射：超出预定义范围的段落\n"
            "            _default_emotion = ('渐显', {'scale': 1.5, 'x': 0, 'y': 0}, '光晕')\n"
            "            _emotion = _emotion_anim_map.get(_scene_slot_idx, _default_emotion)\n"
            "            _anim_name, _motion_vals, _effect_name = _emotion\n"
            "            # 收集情绪特效（effects2 在后面才初始化，先存到临时列表）\n"
            "            _pending_effects.append({'effect_title': _effect_name, 'start': t, 'end': t + slot_us})\n"
            "            _scene_slot_idx += 1\n"
            "            while t < segment_end:\n"
            "                chunk_end = min(segment_end, t + slot_us)\n",
        )
        # 在 _scene_slot_idx 初始化后加 _pending_effects 列表
        _175205_code = _175205_code.replace(
            "        _scene_slot_idx = 0  # 分镜位置计数器\n"
            "        _total_scene_slots = len(scene_audios)  # 总分镜段数\n\n"
            "        for audio_obj in scene_audios:\n",
            "        _scene_slot_idx = 0  # 分镜位置计数器\n"
            "        _total_scene_slots = len(scene_audios)  # 总分镜段数\n"
            "        _pending_effects = []  # 情绪特效暂存（effects2 在后面才定义）\n\n"
            "        for audio_obj in scene_audios:\n",
        )
        # 在 effects2 = [] 之后追加 _pending_effects
        _175205_code = _175205_code.replace(
            "    effects2 = []\n    for _k, _tit in enumerate(body_specs):",
            "    effects2 = []\n"
            "    effects2.extend(_pending_effects)  # 追加情绪匹配特效\n"
            "    for _k, _tit in enumerate(body_specs):",
        )
        # ── 2i. 分镜动画多样化：移除旧的anim_pool逻辑，改用情绪匹配 ──
        # 动态motion：使用情绪匹配的motion值
        # 注意：motion 赋值在 piece_idx 循环内，缩进需要保持一致（20 spaces）
        _175205_code = _175205_code.replace(
            "motion = {\n                        'scale_x': 1.5,\n                        'scale_y': 1.5,\n                        'transform_x': 0.0,\n                        'transform_y': 0.0\n                    }",
            "# 情绪匹配motion：使用上面定义的_motion_vals\n"
            "                    motion = {\n"
            "                        'scale_x': _motion_vals['scale'],\n"
            "                        'scale_y': _motion_vals['scale'],\n"
            "                        'transform_x': _motion_vals['x'],\n"
            "                        'transform_y': _motion_vals['y'],\n"
            "                    }",
        )
        # intro_duration 处理，不需要额外偏移
        # V12模板已有 intro_duration = int(intro_duration) + 3000000
        # 确保揭示窗口足够长（主神图至少展示5s）
        _175205_code = _175205_code.replace(
            "    intro_duration = int(intro_duration) + 3000000  # 加2秒静默开头\n",
            "    intro_duration = int(intro_duration) + 4500000  # 加4.5秒四面八方汇聚开头\n"
            "    # 揭示窗口保底 9.5s（汇聚4.5s后主神图至少展示5s）\n"
            "    intro_duration = max(int(intro_duration), 9500000)\n",
        )
        n175205_node["data"]["inputs"]["code"] = _175205_code

    n174538 = nodes.get("174538")
    if n174538:
        # scale_x/scale_y 设为 1.0：节点级不做缩放，由 scale_keyframes 控制动画
        for _param in n174538["data"]["inputs"].get("inputParameters", []):
            if _param.get("name") in {"scale_x", "scale_y"}:
                _param["input"]["value"] = {
                    "type": "literal",
                    "content": 1.0,
                    "rawMeta": {"type": 4},
                }
        # 174538 不设end时间，由imgs1的end决定持续时长（到视频结束）


    # ── 2c. 背景图层延迟：开场4.5s后才显示 ──
    # bg_layer_001 原模板硬编码了背景图，image_infos 内部有 "start": 0
    # 用户需求：中间一开始是空的，开场动画期间不显示背景
    # 需要同时修改：
    # 1. 外部 start 参数 = 4500000
    # 2. image_infos 内部 JSON 的 start = 4500000
    n_bg_layer = nodes.get("bg_layer_001")
    if n_bg_layer:
        ips = n_bg_layer["data"]["inputs"].setdefault("inputParameters", [])
        existing_names = {p.get("name") for p in ips}

        # 1. 添加/更新外部 start 参数
        if "start" not in existing_names:
            ips.append({
                "name": "start",
                "input": {
                    "type": "integer",
                    "value": {"type": "literal", "content": 4500000, "rawMeta": {"type": 2}}
                }
            })
        else:
            for p in ips:
                if p.get("name") == "start":
                    p["input"]["value"]["content"] = 4500000
                    break

        # 2. 修改 image_infos 内部 JSON 的 start/end
        for p in ips:
            if p.get("name") == "image_infos":
                content_str = p.get("input",{}).get("value",{}).get("content","")
                if content_str:
                    try:
                        import json as _json
                        img_data = _json.loads(content_str)
                        for img in img_data:
                            img["start"] = 4500000  # 背景在开场后才显示
                            img["end"] = 30000000   # 持续到视频结束
                        p["input"]["value"]["content"] = _json.dumps(img_data, ensure_ascii=False)
                    except:
                        pass
                break

    # ── 2d. 轮播图源（150301）：前9张图用于 carousel 四角动画 ──
    # 架构说明：
    # Carousel管线: 150301 → 129767 → 175235 → 151678 (add_images)
    #               159808 (X位置) → 151678.batch.inputLists["item3"]
    #               159809 (Y位置) → 151678.batch.inputLists["item2"] [新增]
    #               151678 → 110647 (X关键帧) → 111477 → 153503 (KFTypePositionX)
    #               151678 → 110648 (Y关键帧) → 111478 → 153504 (KFTypePositionY) [新增]
    # 主神(index 9) 由 imgs1 单独处理 → 174538 渲染放大效果
    #
    # 四角汇聚效果实现：
    # - 9张图从四个对角飞入，汇聚到中间（像打牌）
    # - 需要 transform_x + transform_y 设置初始位置
    # - 需要 KFTypePositionX + KFTypePositionY 关键帧动画
    n150301 = nodes.get("150301")
    if n150301:
        # 只输出前9张图给 carousel，主神(index 9) 由 imgs1 处理
        _carousel_imgs = list(intro_image_urls[:9])
        while len(_carousel_imgs) < 9:
            _carousel_imgs.append(_carousel_imgs[-1] if _carousel_imgs else intro_image_urls[0])
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
            "    // 前9张图：由 carousel 管线渲染四角飞入动画\n"
            "    const outputs = base;\n"
            "    return { outputs };\n"
            "  }"
        )

    # ── 2d-1. 四角位置配置（共9张图，交替从四个对角飞入）──
    # 入场时间：每张图间隔300ms，9张图共2.7s，主神在3.0s飞入
    # 格式：transform_x = X位置, transform_y = Y位置
    # 关键帧：从对角位置动画到中心(0,0)
    _corner_positions_xy = [
        (-1500, -2000),   # 0: 左上角
        (1500, -2000),    # 1: 右上角
        (-1500, 2000),    # 2: 左下角
        (1500, 2000),     # 3: 右下角
        (-2000, -2500),   # 4: 左上角更远（层次感）
        (2000, -2500),    # 5: 右上角更远
        (-2000, 2500),    # 6: 左下角更远
        (2000, 2500),     # 7: 右下角更远
        (-1800, -2200),   # 8: 左上角（最后一张汇聚图）
    ]
    # Stagger the movement onset per corner.
    # Later entries linger longer before they begin moving, so the corners do
    # not all "hit" the center on the same beat.
    _corner_motion_profiles = [
        (1.00, 0.72, 0.38, 0.14, 0.00),
        (1.00, 0.84, 0.52, 0.20, 0.00),
        (1.00, 0.78, 0.44, 0.16, 0.00),
        (1.00, 0.96, 0.68, 0.30, 0.00),
        (1.00, 1.00, 0.74, 0.34, 0.00),
        (1.00, 0.82, 0.48, 0.18, 0.00),
        (1.00, 1.00, 0.86, 0.46, 0.00),
        (1.00, 0.90, 0.62, 0.26, 0.00),
        (1.00, 0.68, 0.34, 0.12, 0.00),
    ]

    def _make_corner_kf_values(value, idx):
        profile = _corner_motion_profiles[idx] if idx < len(_corner_motion_profiles) else _corner_motion_profiles[-1]
        return [str(int(value * ratio)) for ratio in profile[:-1]] + ["0"]

    # ── 2d-2. 更新 159808（X位置源）：9个四角X位置 ──
    n159808 = nodes.get("159808")
    if n159808:
        _x_pos_str = "。".join(str(x) for x, y in _corner_positions_xy)
        for p in n159808["data"]["inputs"].get("inputParameters", []):
            if p.get("name") == "String":
                p["input"]["value"]["content"] = _x_pos_str
                break

    # ── 2d-3. 创建新节点 159809（Y位置源）──
    _y_pos_str = "。".join(str(y) for x, y in _corner_positions_xy)
    node_159809 = {
        "id": "159809",
        "type": "15",
        "meta": {"position": {"x": 13079, "y": 211}},
        "data": {
            "nodeMeta": {
                "description": "四角汇聚Y位置",
                "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-StrConcat-v2.jpg",
                "title": "Y位置坐标",
                "subTitle": "文本处理"
            },
            "inputs": {
                "method": "split",
                "inputParameters": [
                    {
                        "name": "String",
                        "input": {
                            "type": "string",
                            "value": {
                                "type": "literal",
                                "content": _y_pos_str,
                                "rawMeta": {"type": 1}
                            }
                        }
                    }
                ],
                "splitParams": [
                    {
                        "name": "delimiters",
                        "input": {
                            "type": "list",
                            "schema": {"type": "string"},
                            "value": {"type": "literal", "content": ["。"]}
                        }
                    },
                    {
                        "name": "allDelimiters",
                        "input": {
                            "type": "list",
                            "schema": {
                                "type": "object",
                                "schema": [
                                    {"type": "string", "name": "label", "required": True},
                                    {"type": "string", "name": "value", "required": True},
                                    {"type": "boolean", "name": "isDefault", "required": True}
                                ]
                            },
                            "value": {
                                "type": "literal",
                                "content": [
                                    {"isDefault": True, "label": "换行", "value": "\n"},
                                    {"isDefault": True, "label": "制表符", "value": "\t"},
                                    {"isDefault": True, "label": "句号", "value": "。"},
                                    {"isDefault": True, "label": "逗号", "value": "，"},
                                    {"isDefault": True, "label": "分号", "value": "；"},
                                    {"isDefault": True, "label": "空格", "value": " "}
                                ]
                            }
                        }
                    }
                ]
            },
            "outputs": [{"type": "list", "name": "output", "schema": {"type": "string"}, "required": True}]
        }
    }

    # ── 2d-4. 创建新节点 110648（Y关键帧源）──
    # 关键帧格式：5个时间点(0%,10%,25%,35%,99%)的Y位置值，从角落到中心
    # 值：startY, startY*0.7, startY*0.4, startY*0.1, 0
    _y_kf_strs = []
    for idx, (x, y) in enumerate(_corner_positions_xy):
        # Each corner eases in on a slightly different beat.
        kf_vals = _make_corner_kf_values(y, idx)
        _y_kf_strs.append("|".join(kf_vals))
    _y_kf_full_str = "。".join(_y_kf_strs)

    node_110648 = {
        "id": "110648",
        "type": "15",
        "meta": {"position": {"x": 18139, "y": 211}},
        "data": {
            "nodeMeta": {
                "description": "四角汇聚Y关键帧",
                "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-StrConcat-v2.jpg",
                "title": "Y关键帧参数",
                "subTitle": "文本处理"
            },
            "inputs": {
                "method": "split",
                "inputParameters": [
                    {
                        "name": "String",
                        "input": {
                            "type": "string",
                            "value": {
                                "type": "literal",
                                "content": _y_kf_full_str,
                                "rawMeta": {"type": 1}
                            }
                        }
                    }
                ],
                "splitParams": [
                    {
                        "name": "delimiters",
                        "input": {
                            "type": "list",
                            "schema": {"type": "string"},
                            "value": {"type": "literal", "content": ["。"]}
                        }
                    },
                    {
                        "name": "allDelimiters",
                        "input": {
                            "type": "list",
                            "schema": {
                                "type": "object",
                                "schema": [
                                    {"type": "string", "name": "label", "required": True},
                                    {"type": "string", "name": "value", "required": True},
                                    {"type": "boolean", "name": "isDefault", "required": True}
                                ]
                            },
                            "value": {
                                "type": "literal",
                                "content": [
                                    {"isDefault": True, "label": "换行", "value": "\n"},
                                    {"isDefault": True, "label": "制表符", "value": "\t"},
                                    {"isDefault": True, "label": "句号", "value": "。"},
                                    {"isDefault": True, "label": "逗号", "value": "，"},
                                    {"isDefault": True, "label": "分号", "value": "；"},
                                    {"isDefault": True, "label": "空格", "value": " "}
                                ]
                            }
                        }
                    }
                ]
            },
            "outputs": [{"type": "list", "name": "output", "schema": {"type": "string"}, "required": True}]
        }
    }

    # ── 2d-5. 创建新节点 111478（Y偏移量）──
    node_111478 = {
        "id": "111478",
        "type": "5",
        "meta": {"position": {"x": 19639, "y": 211}},
        "data": {
            "nodeMeta": {
                "description": "Y关键帧时间偏移",
                "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Code-v2.jpg",
                "title": "Y关键帧offsets",
                "subTitle": "代码"
            },
            "inputs": {
                "inputParameters": [],
                "code": 'async def main(args: Args) -> Output:\n    return {"output": "0|10|25|35|99"}\n',
                "language": 3,
                "settingOnError": {
                    "switch": False,
                    "processType": 1,
                    "timeoutMs": 60000,
                    "retryTimes": 0
                }
            },
            "outputs": [{"type": "string", "name": "output", "required": False}],
            "version": "v2"
        }
    }

    # ── 2d-6. 创建新节点 153504（KFTypePositionY关键帧生成器）──
    # 完全复制153503结构，只改ctype为KFTypePositionY
    node_153504 = {
        "id": "153504",
        "type": "4",
        "meta": {"position": {"x": 21139, "y": 211}},
        "data": {
            "nodeMeta": {
                "description": "Y轴关键帧生成",
                "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg",
                "title": "Y关键帧生成"
            },
            "inputs": {
                "apiParam": [
                    {"input": {"type": "string", "value": {"content": "7478102722533834778", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiID", "right": {}},
                    {"input": {"type": "string", "value": {"content": "keyframes_infos", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiName", "right": {}},
                    {"input": {"type": "string", "value": {"content": "7522412867740565513", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginID", "right": {}},
                    {"input": {"type": "string", "value": {"content": "剪映小助手数据生成器", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginName", "right": {}},
                    {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginVersion", "right": {}},
                    {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "tips", "right": {}},
                    {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "outDocLink", "right": {}},
                ],
                "batch": {
                    "batchEnable": True,
                    "batchSize": 100,
                    "concurrentSize": 10,
                    "inputLists": [
                        {
                            "name": "item1",
                            "input": {
                                "type": "list",
                                "schema": {"type": "string"},
                                "value": {"type": "ref", "content": {"source": "block-output", "blockID": "110648", "name": "output"}, "rawMeta": {"type": 99}}
                            }
                        },
                        {
                            "name": "segment_infos",
                            "input": {
                                "type": "list",
                                "schema": {
                                    "type": "object",
                                    "schema": [
                                        {"type": "list", "name": "segment_infos", "schema": {"type": "object", "schema": [{"type": "string", "name": "id", "required": False}, {"type": "integer", "name": "start", "required": False}, {"type": "integer", "name": "end", "required": False}]}, "required": False, "description": "segment_ids"},
                                        {"type": "string", "name": "draft_id", "required": False, "description": "草稿ID"},
                                        {"type": "string", "name": "message", "required": False, "description": "消息"},
                                        {"type": "list", "name": "segment_ids", "schema": {"type": "string"}, "required": False, "description": "segment_ids"},
                                    ]
                                },
                                "value": {"type": "ref", "content": {"source": "block-output", "blockID": "151678", "name": "outputList"}, "rawMeta": {"type": 103}}
                            }
                        }
                    ]
                },
                "inputParameters": [
                    {"name": "ctype", "input": {"type": "string", "value": {"type": "literal", "content": "KFTypePositionY", "rawMeta": {"type": 1}}}},
                    {"name": "offsets", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "111478", "name": "output"}, "rawMeta": {"type": 1}}}},
                    {"name": "segment_infos", "input": {"type": "list", "schema": {"type": "object", "schema": [{"type": "string", "name": "id", "required": False}, {"type": "integer", "name": "start", "required": False}, {"type": "integer", "name": "end", "required": False}]}, "value": {"type": "ref", "content": {"source": "block-output", "blockID": "153504", "name": "segment_infos.segment_infos"}, "rawMeta": {"type": 103}}}},
                    {"name": "values", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "153504", "name": "item1"}, "rawMeta": {"type": 1}}}},
                    {"name": "height", "input": {"type": "integer", "value": {"type": "literal", "content": 1080, "rawMeta": {"type": 2}}}},
                    {"name": "width", "input": {"type": "integer", "value": {"type": "literal", "content": 1920, "rawMeta": {"type": 2}}}},
                ],
                "settingOnError": {"processType": 1, "timeoutMs": 180000, "retryTimes": 0}
            },
            "outputs": [
                {"type": "list", "name": "outputList", "schema": {"type": "object", "schema": [{"type": "string", "name": "keyframes_infos", "required": False, "description": "放入add_frames节点"}]}, "required": True},
            ]
        }
    }

    # ── 2d-7. 添加新节点到模板（包含 _temp 元数据）──
    existing_ids = {n["id"] for n in template["json"]["nodes"]}

    # 添加 _temp 元数据（Coze导入验证需要）
    node_159809["_temp"] = {
        "bounds": {"x": 12899, "y": 211, "width": 360, "height": 135.8},
        "externalData": {
            "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-StrConcat-v2.jpg",
            "description": "用于处理多个字符串类型变量的格式",
            "title": "文本处理",
            "mainColor": "#3071F2"
        }
    }
    node_110648["_temp"] = {
        "bounds": {"x": 17959, "y": 211, "width": 360, "height": 135.8},
        "externalData": {
            "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-StrConcat-v2.jpg",
            "description": "用于处理多个字符串类型变量的格式",
            "title": "文本处理",
            "mainColor": "#3071F2"
        }
    }
    node_111478["_temp"] = {
        "bounds": {"x": 19459, "y": 211, "width": 360, "height": 135.8},
        "externalData": {
            "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Code-v2.jpg",
            "description": "编写代码，处理输入变量来生成返回值",
            "title": "代码",
            "mainColor": "#00B2B2"
        }
    }
    # 153504 需要完整的插件元数据（精确复制153503的externalData格式）
    node_153504["_temp"] = {
        "bounds": {"x": 20959, "y": 211, "width": 360, "height": 135.8},
        "externalData": {
            "icon": "https://lf26-appstore-sign.oceancloudapi.com/ocean-cloud-tos/plugin_icon/2109334276542960_1751437477703179450_OPDhBx8e0v.png",
            "apiName": "keyframes_infos",
            "pluginID": "7522412867740565513",
            "pluginProductStatus": 1,
            "pluginProductUnlistType": 0,
            "pluginType": 1,
            "spaceID": "7522406276270358566",
            "inputs": [
                {"description": "关键帧类型", "input": {}, "name": "ctype", "required": True, "type": "string"},
                {"description": "视频高度", "input": {}, "name": "height", "required": False, "type": "integer"},
                {"description": "关键帧位置比例", "input": {}, "name": "offsets", "required": True, "type": "string"},
                {"description": "add_images节点输出", "input": {}, "name": "segment_infos", "required": True, "schema": {"schema": [{"description": "结束时间", "input": {}, "name": "end", "required": True, "type": "integer"}, {"description": "id", "input": {}, "name": "id", "required": True, "type": "string"}, {"description": "开始时间", "input": {}, "name": "start", "required": True, "type": "integer"}], "type": "object"}, "type": "list"},
                {"description": "关键帧值", "input": {}, "name": "values", "required": True, "type": "string"},
                {"description": "视频宽度", "input": {}, "name": "width", "required": False, "type": "integer"},
            ],
            "outputs": [
                {"input": {}, "name": "keyframes_infos", "required": False, "type": "string"},
            ],
            "updateTime": 1772715636,
            "channel_id": 2,
            "commercial_setting": {},
            "latestVersionTs": "0",
            "latestVersionName": "",
            "versionName": "",
            "description": "关键帧数据生成器",
            "title": "keyframes_infos",
            "mainColor": "#CA61FF"
        }
    }

    # ── 2d-7b. 创建新节点 150085（Y关键帧添加节点）──
    # 复制150084结构，用于添加Y轴关键帧
    node_150085 = {
        "id": "150085",
        "type": "4",
        "meta": {"position": {"x": 22459, "y": 211}},
        "data": {
            "nodeMeta": {
                "description": "Y轴关键帧添加",
                "icon": "https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg",
                "title": "添加Y关键帧"
            },
            "inputs": {
                "apiParam": [
                    {"input": {"type": "string", "value": {"content": "7465608338500452404", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiID", "right": {}},
                    {"input": {"type": "string", "value": {"content": "add_keyframes", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "apiName", "right": {}},
                    {"input": {"type": "string", "value": {"content": "7522412867740565513", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginID", "right": {}},
                    {"input": {"type": "string", "value": {"content": "视频合成_剪映小助手", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginName", "right": {}},
                    {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "pluginVersion", "right": {}},
                    {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "tips", "right": {}},
                    {"input": {"type": "string", "value": {"content": "", "dependencies": {"variables": None}, "inputMode": "", "type": "literal"}}, "left": {}, "name": "outDocLink", "right": {}},
                ],
                "batch": {
                    "batchEnable": True,
                    "batchSize": 100,
                    "concurrentSize": 1,
                    "inputLists": [
                        {
                            "name": "item1",
                            "input": {
                                "type": "list",
                                "schema": {
                                    "type": "object",
                                    "schema": [{"type": "string", "name": "keyframes_infos", "required": False, "description": "放入add_frames节点"}]
                                },
                                "value": {
                                    "type": "ref",
                                    "content": {"source": "block-output", "blockID": "153504", "name": "outputList"},
                                    "rawMeta": {"type": 103}
                                }
                            }
                        }
                    ]
                },
                "inputParameters": [
                    {"name": "draft_id", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "119835", "name": "draft_id"}, "rawMeta": {"type": 1}}}},
                    {"name": "keyframes", "input": {"type": "string", "value": {"type": "ref", "content": {"source": "block-output", "blockID": "150085", "name": "item1.keyframes_infos"}, "rawMeta": {"type": 1}}}},
                ],
                "settingOnError": {"processType": 1, "timeoutMs": 180000, "retryTimes": 0}
            },
            "outputs": [
                {"type": "list", "name": "outputList", "schema": {"type": "object", "schema": [{"type": "string", "name": "draft_id", "required": False, "description": "草稿ID"}, {"type": "string", "name": "message", "required": False, "description": "消息"}]}, "required": False},
            ]
        }
    }
    node_150085["_temp"] = {
        "bounds": {"x": 22459, "y": 211, "width": 360, "height": 135.8},
        "externalData": {
            "icon": "https://lf26-appstore-sign.oceancloudapi.com/ocean-cloud-tos/plugin_icon/2109334276542960_1751437477703179450_OPDhBx8e0v.png",
            "apiName": "add_keyframes",
            "pluginID": "7522412867740565513",
            "pluginProductStatus": 1,
            "pluginProductUnlistType": 0,
            "pluginType": 1,
            "spaceID": "7522406276270358566",
            "inputs": [
                {"description": "草稿id", "input": {}, "name": "draft_id", "required": True, "type": "string"},
                {"description": "关键帧数据", "input": {}, "name": "keyframes", "required": True, "type": "string"},
            ],
            "outputs": [
                {"description": "草稿ID", "input": {}, "name": "draft_id", "required": False, "type": "string"},
                {"description": "消息", "input": {}, "name": "message", "required": False, "type": "string"},
            ],
            "updateTime": 1772715636,
            "channel_id": 2,
            "commercial_setting": {},
            "latestVersionTs": "0",
            "latestVersionName": "",
            "versionName": "",
            "description": "添加关键帧",
            "title": "add_keyframes",
            "mainColor": "#CA61FF"
        }
    }

    for new_node in [node_159809, node_110648, node_111478, node_153504, node_150085]:
        if new_node["id"] not in existing_ids:
            template["json"]["nodes"].append(new_node)
            nodes[new_node["id"]] = new_node

    # ── 2d-8. 添加新边（串行拓扑，避免菱形交叉）──
    # 拓扑链路：151678 → 110647 → 111477 → 153503 → 150084 → 110648 → 111478 → 153504 → 150085 → 135573
    # Y 分支串行接在 X 分支之后，不并行汇聚
    edges = template["json"].setdefault("edges", [])
    existing_edge_keys = {
        (e.get("sourceNodeID"), e.get("targetNodeID"), e.get("sourcePortID", ""))
        for e in edges
    }

    # 先移除 150084 → 135573（X分支不再直接连到分镜循环）
    edges[:] = [e for e in edges if not (
        e.get("sourceNodeID") == "150084" and e.get("targetNodeID") == "135573"
    )]

    new_edges = [
        # 159809（Y位置源）必须按 159808 的样子配齐入边+出边，否则没入边
        # 不会被触发，output 不存在，151678 的 item2/transform_y ref 校验失败。
        # V12 模板里 159808 有 119835→159808、175235→159808、159808→151678 三条边。
        # 159808 和 159809 互相无路径，两条并行边到 151678 不构成菱形。
        ("119835", "159809", ""),  # start 触发
        ("175235", "159809", ""),  # 图片管线触发
        ("159809", "151678", ""),  # Y位置数据 → add_images（item2 + transform_y）
        # Y分支串行接在X分支(150084)后面：
        ("150084", "110648", ""),  # X关键帧添加完成 → Y关键帧文本处理
        ("110648", "111478", ""),  # Y关键帧值 → Y偏移
        ("111478", "153504", ""),  # Y偏移 → Y关键帧生成
        ("151678", "153504", ""),  # segment_infos → Y关键帧生成
        ("153504", "150085", ""),  # Y关键帧 → Y关键帧添加节点
        # draft_id 通过 inputLists 引用传递，不需要边（避免与链路形成菱形）
        ("150085", "135573", ""),  # Y关键帧添加 → 分镜循环（唯一入口）
    ]
    for src, tgt, port in new_edges:
        if (src, tgt, port) not in existing_edge_keys:
            edges.append({"sourceNodeID": src, "targetNodeID": tgt, "sourcePortID": port})

    # ── 2d-9. 更新 151678 批处理配置：添加 Y 位置源 ──
    n151678 = nodes.get("151678")
    if n151678:
        batch_config = n151678["data"]["inputs"].setdefault("batch", {"batchEnable": True})
        if "inputLists" not in batch_config:
            batch_config["inputLists"] = []
        # 检查是否已有 item2（Y位置），如果没有则添加
        existing_list_names = {il.get("name") for il in batch_config.get("inputLists", [])}
        if "item2" not in existing_list_names:
            batch_config["inputLists"].append({
                "name": "item2",
                "input": {
                    "type": "list",
                    "schema": {"type": "string"},
                    "value": {
                        "type": "ref",
                        "content": {"source": "block-output", "blockID": "159809", "name": "output"},
                        "rawMeta": {"type": 99}
                    }
                }
            })
        for _il in batch_config.get("inputLists", []):
            if _il.get("name") == "output":
                _il["name"] = "item3"

    # ── 2d-10. 更新单次 inputParameters：恢复 self-ref 到 batch 上下文 ──
    # 批处理节点的 inputParameters 必须 self-ref 自身 itemN（Coze 标准模式：
    # 每轮迭代取当前批元素），不能 ref 上游整条 list。
    # 原模板 image_infos -> 151678.item1，transform_x -> 151678.output。
    # 我们把 inputLists 里的 "output" 改名成 "item3"，这里也要同步把
    # transform_x 的 self-ref 改成 151678.item3，并新增 transform_y -> 151678.item2。
    if n151678:
        ips_151678 = n151678["data"]["inputs"].setdefault("inputParameters", [])
        param_map_151678 = {p.get("name"): p for p in ips_151678}
        for _param in ips_151678:
            if _param.get("name") in {"scale_x", "scale_y"}:
                _param["input"]["value"] = {
                    "type": "literal",
                    "content": INTRO_CARD_SCALE,
                    "rawMeta": {"type": 4},
                }
            elif _param.get("name") == "image_infos":
                _param["input"]["value"] = {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": "151678", "name": "item1"},
                    "rawMeta": {"type": 1},
                }
            elif _param.get("name") == "transform_x":
                _param["input"]["value"] = {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": "151678", "name": "item3"},
                    "rawMeta": {"type": 4},
                }
            elif _param.get("name") == "transform_y":
                _param["input"]["value"] = {
                    "type": "ref",
                    "content": {"source": "block-output", "blockID": "151678", "name": "item2"},
                    "rawMeta": {"type": 4},
                }
        if "transform_y" not in param_map_151678:
            ips_151678.append({
                "name": "transform_y",
                "input": {
                    "type": "number",
                    "value": {
                        "type": "ref",
                        "content": {"source": "block-output", "blockID": "151678", "name": "item2"},
                        "rawMeta": {"type": 4},
                    }
                }
            })

    # ── 2d-10b. [removed] 不要把 153503/153504/150084/150085 的 inputParameters 改成 ref 上游节点 ──
    # 这些节点的 segment_infos / values / keyframes 在 V12 模板里就是 self-ref 到
    # 自身 batch 上下文（如 153503.segment_infos.segment_infos、153503.item1）。
    # 节点定义里已经是正确的 self-ref，覆盖成 ref 上游会让 Coze 校验失败，
    # 报"引用变量不存在"。所以这块覆盖代码整段删掉。
    # 但下面 _ensure_output_fields 还要用这些变量，得显式 get 一下。
    n153503 = nodes.get("153503")
    n153504 = nodes.get("153504")
    n150084 = nodes.get("150084")
    n150085 = nodes.get("150085")

    # 注：原来这里给 151678/153503/153504/150084/150085 的 outputs 显式追加
    # outputList.segment_infos / item1 / segment_infos.segment_infos /
    # item1.keyframes_infos 等 bare-schema 条目，理由是"Coze 校验需要"。
    # 实测（2026-06-01）证明 V12 模板**没有**这些字段也能正常导入，加上反而
    # 让 Coze 拒绝渲染外层连线。已删除。

    # ── 2d-11. 更新 110647（X关键帧源）──
    # X关键帧：各角错峰进场，避免所有图片同一拍贴到中心
    _x_kf_strs = []
    for idx, (x, y) in enumerate(_corner_positions_xy):
        kf_vals = _make_corner_kf_values(x, idx)
        _x_kf_strs.append("|".join(kf_vals))
    _x_kf_full_str = "。".join(_x_kf_strs)

    n110647 = nodes.get("110647")
    if n110647:
        for p in n110647["data"]["inputs"].get("inputParameters", []):
            if p.get("name") == "String":
                p["input"]["value"]["content"] = _x_kf_full_str
                break

    # ── 3. 配音声线 ──
    _voice_id = (voice_id or "").strip() or "7620288417930297386"

    # ── 3a. [removed] 开场白覆盖：保留 V5 模板原文 ──

    if "310628" in nodes:
        for p in (nodes["310628"]["data"]["inputs"].get("inputParameters") or []):
            if p.get("name") == "voice_id":
                p["input"]["value"] = {"type": "literal", "content": _voice_id, "rawMeta": {"type": 1}}
                break
        _ensure_output_fields(nodes["310628"], [
            ("data.link", "string"),
            ("data.duration", "float"),
        ])
    loop_node = nodes.get("135573")
    if loop_node:
        for block in (loop_node.get("blocks") or []):
            if block.get("id") == "102982":
                for p in (block["data"]["inputs"].get("inputParameters") or []):
                    if p.get("name") == "voice_id":
                        p["input"]["value"] = {"type": "literal", "content": _voice_id, "rawMeta": {"type": 1}}
                        break
                _ensure_output_fields(block, [
                    ("data.link", "string"),
                    ("data.duration", "float"),
                ])
                break
    if "129767" in nodes:
        _set_outputs(nodes["129767"], [
            {
                "type": "list",
                "name": "output",
                "schema": {
                    "type": "object",
                    "schema": [
                        {
                            "type": "list",
                            "name": "infos",
                            "schema": {"type": "string"},
                            "required": False,
                        }
                    ],
                },
                "required": False,
            },
        ])
    if "175235" in nodes:
        _set_outputs(nodes["175235"], [
            {"type": "list", "name": "output", "schema": {"type": "string"}, "required": False},
        ])
    if "900001" in nodes:
        _set_outputs(nodes["900001"], [
            {"type": "string", "name": "output", "required": False},
        ])

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

    # ── 边拓扑修复：解决 Coze "并行线路交叉" 错误 ──
    # 这里用本文件内的增强版修复，而不是 topology_fix.py 里那个仅去重的简版。
    _fix_coze_edge_topology(template)

    # ── [DISABLED] 批处理/循环节点自引用修复 ──
    # 原模板有相同的自引用但能导入成功，说明 Coze 内部处理这些自引用
    # 添加额外 outputs 反而会导致 "引用变量不存在" 验证错误
    _ensure_loop_current_item_output(template)
    # _add_batch_inputlists_as_outputs(template)  # 仅在批处理节点需要补自引用输出时再启用

    return sanitize_template_media_urls(template, "god", god_name)
