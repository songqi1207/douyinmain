#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""香烟工作流生成:老红塔山模板 + 2026-07-08 情感独白增量改造。

在原模板基础上按用户定稿做增量修改(不换底):
1. 主题烟对应修复:150301 图库节点按开始节点烟名输出 theme_url,887116 改引它,
   保证中间展示的烟盒就是前端输入的那款(可用 cover_url 覆盖,支持图库外的烟)。
2. 171205 陪跑名单约束在 19 款内置图库烟之内(否则轮播缺图)。
3. 134353 文案改第一人称情感独白(银钗风格提炼要义,不内嵌范文)。
4. 字幕样式:华文行楷/9号/#dfd5d5/行间距-3/位置(-35,-810)。
5. 主题烟封面 70% 缩放,位置(-51,269)(发光描边插件不支持,需剪映手动)。
6. 删除中段非主题烟放大/旋转动画两条链(第一张/第二张封面 = 名单第1、2位,非主题)。
7. 背景视频链整体替换为全片背景图片链(timeline_full 覆盖 0→结尾)。
8. BGM 换 keshi - magnolia。
"""

from copy import deepcopy

from config import CIGARETTE_TEMPLATE_CANDIDATES
from utils.template_loader import load_first_available_template
from utils.media import build_cigarette_match_key
from utils.sanitize import sanitize_template_media_urls
from workflows.common import make_ref
from workflows.god.canvas import ensure_coze_temp_metadata

CIG_BG_IMAGE_URL = "https://a1.boltp.com/2026/07/07/6a4d1d27276dd.png"
CIG_BGM_URL = "https://pub-e79d6e86fa1f4195990ef274a10bb83b.r2.dev/music/keshi%20-%20magnolia_L_compressed.mp3"

CIG_CAPTION_STYLE = {
    "font": "华文行楷",
    "font_size": 9,
    "text_color": "#dfd5d5",
    "line_spacing": -3,
    "transform_x": -35,
    "transform_y": -810,
}
CIG_THEME_TRANSFORM = {"transform_x": -51, "transform_y": 269}

# 与模板 150301 节点内置图库同步维护(陪跑与主题烟盒图都取自这 19 款)
CIG_IMAGE_LIBRARY = [
    "中华", "红塔山", "荷花", "玉溪", "芙蓉王", "黄鹤楼", "娇子", "利群", "南京",
    "泰山", "云烟", "七匹狼", "大前门", "万宝路", "七星", "双喜", "中南海", "黄金叶", "兰州",
]

# 中段"第一张/第二张封面放大±旋转"两条动画链(展示的是名单第1、2位=非主题烟,用户要求删除)
_MID_ANIM_NODES = {
    "182771", "145954", "166620", "483916", "174572", "217444",
    "961933", "100598", "293522", "848424",
    "193758", "828956", "364046", "884316", "357526", "872905",
}
# 背景视频链(整体换成背景图片链)
_BGV_NODES = {"121831", "175734", "182988", "109304"}

# 新增节点 ID(背景图片链)
_BG_URL_ID, _BG_LIST_ID, _BG_INFO_ID, _BG_ADD_ID = "990001", "990002", "990003", "990004"

PROMPT_171205 = """# 角色
你是香烟视频的开场名单生成器。用户会给出一款香烟,你从内置可选名单里挑 7 款陪跑,加上用户输入的那款,组成 8 款名单。

## 可选名单(陪跑只能从这里选,一款都不能超出)
中华、红塔山、荷花、玉溪、芙蓉王、黄鹤楼、娇子、利群、南京、泰山、云烟、七匹狼、大前门、万宝路、七星、双喜、中南海、黄金叶、兰州

## 技能
1. 用户输入{{input}}固定放在第 3 位。
2. 其余 7 款从可选名单中随机挑选,不得与用户输入{{input}}相同,彼此不重复。

## 限制
- 只输出香烟的原名,一款一行,不需要输出任何其他文字内容。
- 所输出的内容以数组化的格式放在数组的 output 中。
- 不能偏离框架要求。"""

PROMPT_134353 = """# 角色
你是香烟赛道的情感独白文案作者。用户给出一款香烟的名字,你写一篇可以直接配音的第一人称独白:借这款烟,对心里那个“你”说话。不写百科资料,不写带货话术,不写品鉴测评。

## 输出
只输出纯文案段落,不做任何解释、不加标题、不加序号、不输出数组。

## 固定开头
文案第一句固定为:每天认识一种香烟之XX。(XX 为用户输入的香烟名,以句号收尾)

## 写法要义
- 通篇是对“你”的第一人称独白:深情、克制、干净,像把攒了很久的话慢慢说出口。
- 古典韵味与现代生活细节交织:栏目句之后,用一句有古意的短句或轻设问起兴,并立刻落到这款烟专属的意象上(名字的字面、包装的颜色与图案、系列的说法)。
- 核心手法是意象转译:包装的颜色与线条,写成与“你”有关的某个瞬间;口感的初息、中段、尾韵,写成感情的进程(克制、心动、余味);名字与典故,化成两人之间的私语或心愿。
- 意象必须具体可入画:写光、温度、动作、物件,拒绝空泛抒情与形容词堆砌。
- 心意慢慢升温:前面藏着说,越往后越按不住,结尾把心意说破,落到“往后与你”的具体盼望,用一个画面收束,克制不腻。
- 意象必须从这款烟自己的名字、包装、色彩、典故里生长出来;换一款烟,整篇意象必须跟着换,禁止套用其他烟的梗。

## 硬性限制
- 全文 200 到 300 字。
- 句子偏短,一句一意,每句都以句号、问号或感叹号收束,适合逐句出字幕。
- 烟的名字、包装、图案、典故必须符合事实;拿不准的细节宁可写虚(光、气息、温度),禁止编造年份、价格、销量数据。
- 口感只作情感隐喻,不写“好抽、提神、解乏、值得一试”这类品鉴与诱导表述,不劝人吸烟。
- 禁止评论区、点赞、关注等引导词,禁止祝福模板,禁止百科腔与AI套话。"""

CODE_127963 = '''from typing import TypedDict, Dict, Any, List

# 定义输入参数的类型
class Args(TypedDict):
    params: Dict[str, Any]

# 定义输出结果的类型
class Output(TypedDict):
    timeline1: List[dict]
    timeline2: List[dict]
    timeline3: List[dict]
    timeline4: List[dict]
    timeline_full: List[dict]


async def main(args: Args) -> Output:
    try:
        params = args["params"]
        input_data = params["input"]

        if not input_data:
            raise ValueError("Input data list is empty")

        timeline1 = [input_data[0]]
        timeline_full = [{"start": 0, "end": input_data[-1]["end"]}]

        if len(input_data) > 1:
            second_start = input_data[1]["start"]
            last_end = input_data[-1]["end"]
            timeline2 = [{"start": second_start, "end": last_end}]

            end_value = second_start + 1500000
            timeline3 = [{"start": second_start, "end": end_value}]

            # 新增 timeline4 的逻辑
            first_end = input_data[0]["end"]
            timeline4 = [{"start": 1560000, "end": first_end}]
        else:
            timeline2 = []
            timeline3 = []
            timeline4 = []

        ret: Output = {
            "timeline1": timeline1,
            "timeline2": timeline2,
            "timeline3": timeline3,
            "timeline4": timeline4,
            "timeline_full": timeline_full
        }
        return ret
    except KeyError as e:
        raise ValueError(f"Missing required key in input: {str(e)}") from e
    except Exception as e:
        raise Exception(f"Error in main: {str(e)}") from e
'''


def _literal(value, raw_type):
    return {"type": "literal", "content": value, "rawMeta": {"type": raw_type}}


def _params(node):
    return node["data"]["inputs"]["inputParameters"]


def _param(node, name):
    for p in _params(node):
        if p.get("name") == name:
            return p
    return None


def _set_literal(node, name, value):
    raw_type = 1 if isinstance(value, str) else 2
    p = _param(node, name)
    if p is None:
        _params(node).append({
            "name": name,
            "input": {"type": "string" if isinstance(value, str) else "integer",
                      "value": _literal(value, raw_type)},
        })
    else:
        p["input"]["value"] = _literal(value, raw_type)


def _set_system_prompt(node, text):
    for p in node["data"]["inputs"]["llmParam"]:
        if p.get("name") == "systemPrompt":
            p["input"]["value"]["content"] = text
            return
    raise ValueError(f"节点 {node['id']} 没有 systemPrompt")


def _apply_monologue_v2(template, cigarette_name, cover_url=""):
    """对老红塔山模板做 2026-07-08 定稿的增量改造,返回 warning(或 None)。"""
    nodes = template["json"]["nodes"]
    edges = template["json"]["edges"]
    byid = {n["id"]: n for n in nodes}
    for required in ("150301", "887116", "175877", "557577", "127963", "113060",
                     "171205", "134353", "148842", "136720", "737556", "368825"):
        if required not in byid:
            raise ValueError(f"模板缺少节点 {required},疑似模板版本不符")

    warning = None

    # ── 1) 主题烟对应:150301 输出 theme_url ──
    n301 = byid["150301"]
    if _param(n301, "zhuti") is None:
        _params(n301).append({
            "name": "zhuti",
            "input": {"type": "string", "value": make_ref("100001", "xiangyan_name")},
        })
    outs301 = n301["data"].setdefault("outputs", [])
    if not any(o.get("name") == "theme_url" for o in outs301):
        outs301.append({"type": "string", "name": "theme_url", "required": False})
    code301 = n301["data"]["inputs"]["code"]
    if "theme_url" not in code301:
        anchor = "outputs: imageUrls"
        if code301.count(anchor) != 1:
            raise ValueError(f"150301 代码锚点出现 {code301.count(anchor)} 次(应为1)")
        n301["data"]["inputs"]["code"] = code301.replace(
            anchor,
            'outputs: imageUrls,\n    theme_url: (typeof params.zhuti === "string" '
            '&& cigaretteMap[params.zhuti.trim()]) || imageUrls[2] || imageUrls[0] || ""',
        )

    # 887116 改引 theme_url(有 cover_url 则直接用外部图)
    n887 = byid["887116"]
    p887 = _param(n887, "String1")
    if cover_url:
        p887["input"]["value"] = _literal(cover_url, 1)
    else:
        val = p887["input"]["value"]
        if val.get("type") == "ref" and val["content"].get("blockID") == "150301":
            val["content"]["name"] = "theme_url"
        elif val.get("type") != "literal":
            raise ValueError("887116 String1 引用结构异常")
        if cigarette_name not in CIG_IMAGE_LIBRARY:
            warning = (
                f"「{cigarette_name}」不在内置 19 款烟盒图库中,中间主题烟图会回退为陪跑名单第 3 张;"
                "建议在「烟盒图片链接」里提供这款烟的烟盒图后重新生成"
            )

    # ── 2) 陪跑名单约束 + 3) 独白文案 ──
    _set_system_prompt(byid["171205"], PROMPT_171205)
    _set_system_prompt(byid["134353"], PROMPT_134353)

    # ── 4) 字幕样式 ──
    n_cap = byid["175877"]
    for key, value in CIG_CAPTION_STYLE.items():
        _set_literal(n_cap, key, value)

    # ── 5) 主题烟位置 ──
    n_theme = byid["557577"]
    for key, value in CIG_THEME_TRANSFORM.items():
        _set_literal(n_theme, key, value)

    # ── 6) 删除中段非主题动画链,桥接控制流 ──
    template["json"]["nodes"] = [n for n in nodes if n["id"] not in _MID_ANIM_NODES]
    template["json"]["edges"] = [
        e for e in edges
        if e.get("sourceNodeID") not in _MID_ANIM_NODES
        and e.get("targetNodeID") not in _MID_ANIM_NODES
    ]
    nodes = template["json"]["nodes"]
    edges = template["json"]["edges"]
    edges.append({"sourceNodeID": "639486", "targetNodeID": "245595"})
    edges.append({"sourceNodeID": "887116", "targetNodeID": "142783"})

    # ── 7) 背景视频链 → 全片背景图片链 ──
    #   时间线:127963 重写,新增 timeline_full(0→结尾)
    n963 = byid["127963"]
    n963["data"]["inputs"]["code"] = CODE_127963
    outs963 = n963["data"].setdefault("outputs", [])
    if not any(o.get("name") == "timeline_full" for o in outs963):
        outs963.append({
            "type": "list", "name": "timeline_full",
            "schema": {"type": "object", "schema": []}, "required": False,
        })

    #   四个新节点:URL文本 → 列表化 → imgs_infos → add_images(克隆现有同类节点)
    n_url = deepcopy(byid["121831"])
    n_url["id"] = _BG_URL_ID
    n_url["data"]["nodeMeta"]["title"] = "背景图片"
    _set_literal(n_url, "String1", CIG_BG_IMAGE_URL)

    n_list = deepcopy(byid["737556"])
    n_list["id"] = _BG_LIST_ID
    n_list["data"]["nodeMeta"]["title"] = "背景图片列表化"
    _param(n_list, "obj")["input"]["value"] = make_ref(_BG_URL_ID, "output")

    n_info = deepcopy(byid["368825"])
    n_info["id"] = _BG_INFO_ID
    n_info["data"]["nodeMeta"]["title"] = "输入前背景图片格式整理"
    _param(n_info, "imgs")["input"]["value"] = make_ref(_BG_LIST_ID, "infos")
    _param(n_info, "timelines")["input"]["value"] = make_ref("127963", "timeline_full")
    n_info["data"]["inputs"]["inputParameters"] = [
        p for p in _params(n_info) if p.get("name") not in ("in_animation", "in_animation_duration")
    ]

    n_add = deepcopy(byid["557577"])
    n_add["id"] = _BG_ADD_ID
    n_add["data"]["nodeMeta"]["title"] = "添加全片背景图片"
    _param(n_add, "image_infos")["input"]["value"] = make_ref(_BG_INFO_ID, "infos")
    _set_literal(n_add, "scale_x", 1)
    _set_literal(n_add, "scale_y", 1)
    _set_literal(n_add, "transform_x", 0)
    _set_literal(n_add, "transform_y", 0)

    #   删除背景视频链,插入背景图片链(位于草稿链最前,保证背景在最底层)
    template["json"]["nodes"] = [n for n in nodes if n["id"] not in _BGV_NODES]
    template["json"]["edges"] = [
        e for e in edges
        if e.get("sourceNodeID") not in _BGV_NODES
        and e.get("targetNodeID") not in _BGV_NODES
    ]
    nodes = template["json"]["nodes"]
    edges = template["json"]["edges"]
    nodes.extend([n_url, n_list, n_info, n_add])
    edges.append({"sourceNodeID": "113060", "targetNodeID": "171205"})
    edges.append({"sourceNodeID": "148842", "targetNodeID": _BG_URL_ID})
    edges.append({"sourceNodeID": _BG_URL_ID, "targetNodeID": _BG_LIST_ID})
    edges.append({"sourceNodeID": _BG_LIST_ID, "targetNodeID": _BG_INFO_ID})
    edges.append({"sourceNodeID": _BG_INFO_ID, "targetNodeID": _BG_ADD_ID})
    edges.append({"sourceNodeID": _BG_ADD_ID, "targetNodeID": "136720"})

    # ── 8) BGM ──
    _set_literal(byid["113060"], "String1", CIG_BGM_URL)

    # ── 自校验 ──
    ids = set()
    for n in nodes:
        ids.add(n["id"])
        for b in n.get("blocks") or []:
            ids.add(b.get("id"))
    dangling = []

    def _walk(obj, owner):
        if isinstance(obj, dict):
            if obj.get("source") == "block-output" and obj.get("blockID") not in ids:
                dangling.append(f"{owner}←{obj.get('blockID')}.{obj.get('name')}")
            for v in obj.values():
                _walk(v, owner)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, owner)

    for n in nodes:
        _walk(n.get("data"), n["id"])
    if dangling:
        raise ValueError(f"存在悬空引用: {dangling[:5]}")
    for e in edges:
        if e.get("sourceNodeID") not in ids or e.get("targetNodeID") not in ids:
            raise ValueError(f"存在悬空边: {e}")
    compile(CODE_127963, "127963", "exec")

    return warning


def generate_cigarette_workflow(cigarette_name, cover_url=""):
    """
    生成香烟工作流(老模板 + 情感独白增量改造)。
    返回 (template, warning)。cover_url 非空时用它作为中间主题烟盒图。
    """
    template = load_first_available_template(CIGARETTE_TEMPLATE_CANDIDATES)
    nodes = {n.get("id"): n for n in template.get("json", {}).get("nodes", []) if isinstance(n, dict)}

    for node in template["json"]["nodes"]:
        if node["id"] == "100001":
            outputs = node["data"].get("outputs", [])
            for output in outputs:
                if output["name"] == "xiangyan_name":
                    output["value"] = cigarette_name
                    output["defaultValue"] = cigarette_name
                elif output["name"] == "left_top":
                    output["value"] = "吸烟有害身体健康"
                    output["defaultValue"] = "吸烟有害身体健康"
                elif output["name"] == "left":
                    output["value"] = "未成年人禁止吸烟"
                    output["defaultValue"] = "未成年人禁止吸烟"

    if "900001" in nodes:
        end_data = nodes["900001"].setdefault("data", {})
        end_inputs = end_data.setdefault("inputs", {})
        end_inputs["terminatePlan"] = "returnVariables"
        end_data["outputs"] = [
            {"type": "string", "name": "output", "required": False, "description": "剪映草稿 draft_id"},
            {"type": "string", "name": "tts_code", "required": False, "description": "配音接口状态码（0 常为成功）"},
            {"type": "string", "name": "tts_msg", "required": False, "description": "配音接口消息（失败时看这里）"},
        ]
        end_inputs["inputParameters"] = [
            {"name": "output", "input": {"type": "string", "value": make_ref("148842", "draft_id")}},
            {"name": "tts_code", "input": {"type": "string", "value": make_ref("163300", "code")}},
            {"name": "tts_msg", "input": {"type": "string", "value": make_ref("163300", "msg")}},
        ]

    warning = _apply_monologue_v2(template, cigarette_name, cover_url=cover_url)

    ensure_coze_temp_metadata(template)
    match_key = build_cigarette_match_key(cigarette_name)
    template = sanitize_template_media_urls(template, "cigarette", match_key)
    return template, warning
