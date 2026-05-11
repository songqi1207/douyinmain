#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局配置常量与环境变量。
其他模块统一 ``from config import ...`` 获取配置值。
"""

import logging
import os
from pathlib import Path

# ------------------------------------------------------------------
# .env 加载（放在最顶部，确保后续 os.getenv 能读到 .env 内容）
# ------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# ------------------------------------------------------------------
# 项目根目录
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

# ------------------------------------------------------------------
# 图床 Token，用于封面上传（SM.MS：https://smms.app 注册后获取）
# 环境变量名：CDN_TOKEN 或 BOLTP_TOKEN（兼容旧名）
# ------------------------------------------------------------------
CDN_TOKEN = (os.getenv("CDN_TOKEN") or os.getenv("BOLTP_TOKEN") or "").strip()
# 图床储存 ID：boltp.com 免费用户=2，VIP=3
CDN_STORAGE_ID = int(os.getenv("CDN_STORAGE_ID", "2"))
# 图床过期天数：正数=保留天数，<=0 表示不传 expired_at（由图床按默认策略存；公开图通常不过期）
CDN_EXPIRE_DAYS = int(os.getenv("CDN_EXPIRE_DAYS", "30"))
# 是否自动移除 EXIF（默认开，避免本机 GPS / 设备信息泄露到公网）
CDN_REMOVE_EXIF = os.getenv("CDN_REMOVE_EXIF", "true").strip().lower() not in ("0", "false", "no", "off")

# ------------------------------------------------------------------
# 米核 Key
# ------------------------------------------------------------------
_MIHE_DEFAULT = "10de5318-af20-472f-a3a1-bd334bea8ccc"
_MIHE_ENV = (os.getenv("MIHE_KEY") or "").strip()
MIHE_KEY = _MIHE_ENV or _MIHE_DEFAULT
# 写入各工作流「开始」节点里 mihe_key 字段的说明（Coze 里可见）
MIHE_KEY_OUTPUT_DESC = (
    "米核 API Key。注册/充值：https://www.miheai.com/?share_id=14304\n"
    "若即梦生图报错为额度不足、余额用完、次数用尽、密钥无效、鉴权失败或 401/403，"
    "请到米核后台充值或更换新 Key，并在部署环境变量 MIHE_KEY 与本字段中同步填写。"
)
# 网页横幅提示（不输出密钥内容；说明「本站无法检测额度」避免用户误解）
MIHE_KEY_HINT_UI = (
    "【重要】本网站只生成工作流 JSON，不会在服务器上调用米核即梦，因此这里无法提前提示「Key 额度用尽」；"
    "是否欠费、余额不足，只有在 Coze 里真正跑即梦生图时才会报错。"
    "若即梦提示额度/鉴权错误，请到 https://www.miheai.com 充值或更换 Key，并同步环境变量 MIHE_KEY 后重新下载流程。"
)
# 米核即梦等接口提示词上限约 800 字；默认取 640 留余量（循环里还会拼接远景/中景后缀）
MIHE_PROMPT_MAX_CHARS = max(120, min(int(os.getenv("MIHE_PROMPT_MAX_CHARS", "640")), 800))
# 插入在绘画 LLM 与即梦之间的代码节点 ID（与神话工作流共用）
MIHE_PROMPT_CLAMP_NODE_ID = "201800"

# ------------------------------------------------------------------
# LLM System Prompt：书籍插图
# ------------------------------------------------------------------
BOOK_ILLUSTRATION_SYSTEM_PROMPT = (
    "# 角色\n"
    "你是书籍视觉提示词创作者，服务于「每天认识一本书」短视频系列。\n"
    "只输出「一段」可直接用于即梦的中文提示词。\n\n"
    "## 任务\n"
    "根据书名《{{input}}》，写一幅融合书中核心情感与气质的画面描述。\n\n"
    "## 四阶段情感视觉映射\n"
    "画面应体现书中情感弧线的精华，可根据书的主题侧重以下视觉意象：\n"
    "- 巅峰：广角构图，饱和暖色调（金色、橙色），强烈光影对比\n"
    "- 转折与失落：冷色调（深蓝、紫色），物体破碎或虚化\n"
    "- 寻觅与追寻：慢镜头质感，中景特写，柔和冷光，怀旧氛围\n"
    "- 思想的升华：远景宏大环境，哲学象征物，渐变柔焦\n\n"
    "## 硬性要求（违反会导致生图失败）\n"
    "- 只使用中文；禁止英文段落、禁止中英双语各写一遍\n"
    "- 全文连标点在内不超过 420 字；米核接口硬上限约 800 字，必须留余量\n"
    "- 可简写：构图、光线、色调、氛围、器物（书页、笔墨、窗光等）\n"
    "- 禁止涉政、色情、暴力直白描写；不要出现字幕、水印、二维码等字样\n\n"
    "## 输出\n"
    "- 只输出提示词正文，不要标题、不要解释。"
)

# ------------------------------------------------------------------
# 默认音乐
# ------------------------------------------------------------------
BGM_DEFAULT = ""
CIGARETTE_BGM_DEFAULT = "https://p26-bot-workflow-sign.byteimg.com/tos-cn-i-mdko3gqilj/f3c5163a0ad44d06a296a26f48a2dd99.MP3~tplv-mdko3gqilj-image.image?rk3s=81d4c505&x-expires=1803121266&x-signature=UMnUkC%2BoKa7YB9YS1Rt2%2BRuwYyo%3D"

# ------------------------------------------------------------------
# 封面图片保存目录
# ------------------------------------------------------------------
COVER_DIR = os.path.join(os.path.dirname(__file__), 'covers')
os.makedirs(COVER_DIR, exist_ok=True)

# ------------------------------------------------------------------
# 书籍片头轮播默认封面（公网 URL，用于开场快速闪过多本书）
# ------------------------------------------------------------------
BOOK_INTRO_COVERS = [
    "https://a1.boltp.com/2026/05/10/6a005a3d71714.jpg",   # 三体
    "https://a1.boltp.com/2026/05/10/6a005a3f49dad.jpg",   # 活着
    "https://a1.boltp.com/2026/05/10/6a005a413f2b1.jpg",   # 红楼梦
    "https://a1.boltp.com/2026/05/10/6a005a4349f3a.jpg",   # 西游记
    "https://a1.boltp.com/2026/05/10/6a005a452cfdc.jpg",   # 三国演义
    "https://a1.boltp.com/2026/05/10/6a005a46dbf2c.jpg",   # 围城
    "https://a1.boltp.com/2026/05/10/6a005a491012b.jpg",   # 小王子
    "https://a1.boltp.com/2026/05/10/6a005a4acf865.jpg",   # 挪威的森林
]

# ------------------------------------------------------------------
# 视频预览
# ------------------------------------------------------------------
VIDEO_PREVIEW_PATTERNS = {
    "book": ["每天认识一本书-视频.mov", "每天认识一本书*.mov", "每天认识一本书*.mp4"],
    "cigarette": ["每天认识一款香烟.mov", "每天认识一款香烟*.mov", "每天认识一款香烟*.mp4"],
    "god": ["每天认识一个神.mov", "每天认识一个神*.mov", "每天认识一个神*.mp4"],
}

PREVIEW_VIDEO_URLS = {
    "book": os.getenv("PREVIEW_VIDEO_URL_BOOK", "").strip(),
    "cigarette": os.getenv("PREVIEW_VIDEO_URL_CIGARETTE", "").strip(),
    "god": os.getenv("PREVIEW_VIDEO_URL_GOD", "").strip(),
}

# ------------------------------------------------------------------
# URL 校验
# ------------------------------------------------------------------
BLOCKED_MEDIA_HOSTS = {
    "p3-heycan-jy-sign.byteimg.com",
}

# 反盗链图源：本地爬虫带 Referer 能下，但 Coze/剪映草稿解析端下载器不带 Referer，一律 403。
# 这些域名的链接「不应」被写进 cover_source_url，也不应出现在 Coze 工作流 pic 字段里。
HOTLINK_PROTECTED_HOSTS = (
    "doubanio.com",       # img1/img2/img3/img9.doubanio.com
    "bkimg.cdn.bcebos.com",
    "bkimg.baidu.com",
)


def is_hotlink_protected_url(url):
    """粗略判断 URL 所属域名是否反盗链，Coze/剪映侧不能直取。"""
    if not url or not isinstance(url, str):
        return False
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(url).hostname or "").lower()
        return any(host == h or host.endswith("." + h) or h in host for h in HOTLINK_PROTECTED_HOSTS)
    except Exception:
        return False

PLACEHOLDER_MEDIA_HOSTS = {
    "a.png",
    "a.jpg",
    "a.jpeg",
    "a.webp",
    "a.mp4",
    "example.com",
    "example.org",
    "localhost",
}

# ------------------------------------------------------------------
# 香烟工作流
# ------------------------------------------------------------------
CIGARETTE_TEMPLATE_CANDIDATES = [
    "temp/template/每天认识一款香烟_红塔山.txt",
    "每天认识一款香烟.txt",
]

CIGARETTE_STYLE_HINTS = [
    (("中华", "芙蓉王", "黄鹤楼"), "hongjin_shangwu"),
    (("玉溪", "云烟", "南京"), "qingxin_wenya"),
    (("利群", "苏烟", "双喜"), "chenwen_jingzhi"),
    (("红塔山", "白沙", "七匹狼"), "huoli_fugu"),
]

# ------------------------------------------------------------------
# HTTP 请求头（爬虫共用）
# ------------------------------------------------------------------
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def setup_crawler_logging():
    """
    书籍 / 百科 爬虫日志输出到终端。
    环境变量 CRAWLER_LOG_LEVEL：DEBUG / INFO（默认）/ WARNING / ERROR。
    幂等：已配置过则跳过，避免重复挂 handler；get_book_info 入口也会调用，不依赖仅 app 启动时初始化。
    """
    log = logging.getLogger("crawlers")
    if log.handlers:
        return
    level_name = (os.getenv("CRAWLER_LOG_LEVEL") or "INFO").strip().upper()
    lvl = getattr(logging, level_name, logging.INFO)
    log.setLevel(lvl)
    h = logging.StreamHandler()
    h.setLevel(lvl)
    h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    )
    log.addHandler(h)
    log.propagate = False


def print_startup_info():
    """启动时打印米核 Key 配置状态。"""
    setup_crawler_logging()
    print(
        f"[dy] 书籍/百科爬虫：终端可见 logger crawlers.*；更细设 CRAWLER_LOG_LEVEL=DEBUG。"
        f" 网页「搜索书籍」会在结果里带 _fetch_trace（或设 CRAWLER_API_TRACE=1）。"
    )
    if MIHE_KEY:
        print(f"[mihe] MIHE_KEY 已配置（长度 {len(MIHE_KEY)}）。若你刚改过 Key 仍像旧的，请先重建/重启容器；旧版下载的工作流文件里也会嵌旧 Key。")
    else:
        print("[mihe] MIHE_KEY 未配置，请设置环境变量或 .env。")
    if CDN_TOKEN:
        print(
            f"[cdn] CDN_TOKEN 已配置（长度 {len(CDN_TOKEN)}）。"
            f" storage_id={CDN_STORAGE_ID} expire_days={CDN_EXPIRE_DAYS} remove_exif={CDN_REMOVE_EXIF}。"
            f" 本地封面会转传至 boltp 获取公网 URL 给 Coze/剪映使用。"
        )
    else:
        print(
            "[cdn] CDN_TOKEN 未配置。本地生成的工作流封面会指向 http://<本机>/api/cover/...，"
            "如 Coze 云端无法回访本机（非公网/未设 PUBLIC_BASE_URL），剪映草稿会因下载封面失败而报错。"
            " 推荐：在 .env 或环境变量里配 CDN_TOKEN（boltp.com 的 API Token）。"
        )
    print("[dy] 若刚改了 workflows/god/builder.py 但生成的 txt 仍无 last_img_end：请确认在此目录运行的是当前代码；Docker 部署需执行 docker compose build --no-cache && docker compose up -d。")
