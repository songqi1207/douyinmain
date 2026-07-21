"""Published Coze parameter mapping for the god workflow."""

from __future__ import annotations

from typing import Any

from config import GOD_BGM_DEFAULT
from workflows.god.intro_images import GOD_APPEARANCE_TRAITS


DEFAULT_GOD_VOICE_ID = "7620288417930297386"
_GENERIC_APPEARANCE = "中国神话体系中的正神，冠服、法器与神态符合古籍记载，庄严神圣"
_STYLE_BODY = (
    "核心风格：中国传统工笔重彩、永乐宫壁画风格、敦煌壁画风格、道教神仙图谱风格、"
    "佛教壁画风格、《三教源流搜神大全》插图风格、《历代神仙通鉴》古籍插画风格、"
    "博物馆藏品级古画质感、矿物颜料绘制、宣纸肌理、细腻线描、高密度纹样、神圣庄严、"
    "空灵神秘、仙风道骨、东方神性美学。构图：横屏16:9、敦煌经变画式超大全景，"
    "主体神明是远处的点景小人，占画面高度不到十五分之一，精确位于画面正中央、"
    "上下左右留白对称，四周铺满山川云海仙宫星空等宏大风景，禁止近景、半身、特写、"
    "居中巨像。色彩体系：低饱和做旧壁画色，以赭石、土黄、灰青、黛绿、烟褐、月白为主，"
    "像氧化褪色的敦煌旧壁画，整体灰调厚重高级；禁止高饱和大红大蓝大金与荧光感，"
    "金色只作小面积点缀。背景元素按神格自动选择：祥云、仙宫、天门、神山、昆仑、星空、"
    "银河、仙鹤、凤凰、龙、麒麟、神兽、流光、神纹、法阵、古代楼阁、云海、远山、灵气。"
    "人物要求：符合对应神格，人物太小不刻画面容，身份靠体态剪影、法器轮廓与神光颜色表达。"
    "动作要求：人物极小，只需一个远观可辨的姿态剪影（踏云、抬臂、拂袖、端坐、俯瞰等），"
    "相邻画面姿态与取景必须明显不同，画面地点必须跟随分镜文案。服装要求：人物太小无需"
    "服饰细节，只写袍服颜色与飘带的远观剪影。光影要求：神光自然散发，如古代壁画中神明降临，"
    "非摄影棚灯光、非电影打光、非游戏光效。品质要求：Ultra detailed, Masterpiece, Museum quality, "
    "Traditional Chinese deity painting, Ancient Chinese mural, Chinese mythology illustration, "
    "Chinese immortal portrait, Highly detailed, Epic composition, Divine atmosphere, Unique face, "
    "Not same character。负面提示词：现代服装、现代建筑、现代首饰、欧美风、二次元、动漫、"
    "网红脸、AI模板脸、同一张脸、赛博朋克、科幻、3D、CG、游戏原画、Midjourney风、摄影、"
    "写实照片、畸形手指、低清晰度、模糊、水印、文字、Logo、字幕。"
)


def build_god_provider_parameters(inputs: dict[str, Any]) -> dict[str, Any]:
    topic = str(inputs.get("god_name") or inputs.get("theme") or inputs.get("zhuti") or "").strip()
    appearance = str(inputs.get("description") or "").strip()
    if not appearance:
        appearance = GOD_APPEARANCE_TRAITS.get(topic) or _GENERIC_APPEARANCE
    style = str(inputs.get("fengge") or "").strip()
    if not style:
        style = f"你是一位中国神话绘画大师。请根据用户输入的神仙名称，生成一幅符合中国传统神话体系的神仙画像。主神形象必须贴合：{topic}为{appearance}。{_STYLE_BODY}"

    script = str(inputs.get("script") or inputs.get("wenan") or "").strip()
    if not script:
        script = f"{topic}的身份背景、成名经历、最重要的经历、记忆点的传说、象征能力与文化影响"

    count = inputs.get("scene_count", inputs.get("shuliang", 10))
    try:
        count = max(1, min(int(count), 22))
    except (TypeError, ValueError):
        count = 10

    return {
        "audio": str(inputs.get("audio_url") or inputs.get("audio") or GOD_BGM_DEFAULT).strip(),
        "cankao": str(inputs.get("cankao") or "").strip(),
        "fengge": style,
        "shuliang": str(count),
        "wenan": script,
        "yinse": str(inputs.get("voice_id") or inputs.get("yinse") or DEFAULT_GOD_VOICE_ID).strip(),
        "zhuti": topic,
    }
