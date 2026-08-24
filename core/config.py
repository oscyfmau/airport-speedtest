#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置与常量（单一数据源；v4.10 起为真定义模块）"""
import os

VERSION = "4.43.0"  # SemVer：主版本.次版本.修订号（v4.43.0 MiaoKo 蓝绿视觉改版）


# 产物累积清理默认值（v4.31.0，core/profiles.cleanup_outputs；settings 持久化可覆盖）
KEEP_REPORTS_DEFAULT = 30    # output/ 保留最近 N 份 PNG+JSON 配对
KEEP_LOGS_DAYS_DEFAULT = 30  # log/ 保留最近 N 天


# 快速检测（v4.30.0，quick 模式）：并行近似测速，速度只作量级参考
QUICK_DOWNLOAD_URL = "https://speed.cloudflare.com/__down?bytes=5000000"  # 单源 5MB
QUICK_WINDOW = 5               # 测速窗口上限秒数
QUICK_WORKERS = 4              # 并行 worker 数（并行互抢带宽，近似值）
QUICK_TCP_TIMEOUT = 2.0        # 直连 TCP 单次超时（仅 1 次尝试，无隧道探测）
QUICK_STREAMING_IDS = ("youtube", "netflix", "disney", "chatgpt")  # 4 核心平台


# 节点档案（v4.29.0，core/profiles.py）：状态机与稳定性分层阈值
SILENT_RUNS = 3               # 连续未出现 N 次 run → 沉寂
SILENT_DAYS = 14              # last_seen 超过 N 天 → 沉寂
EVIDENCE_MAX = 10             # 每档案保留最近证据条数（更早折叠进 fold）
RUNS_MAX = 50                 # profiles.runs 保留最近条数
STABILITY_APPEAR_RATIO = 0.8  # 常青树/过山车：近 N 次出现率门槛
STABILITY_SIGMA = 0.3         # 波动门槛：σ/均值 ≥ 0.3 → 过山车
NEW_FACE_MIN_EVIDENCE = 3     # 证据 < 3 条 → 新面孔


MIHOMO_REPO = "MetaCubeX/mihomo"


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


_BASE_DIR = os.path.dirname(_SCRIPT_DIR) if os.path.basename(_SCRIPT_DIR) in ("core", "src") else _SCRIPT_DIR


MIHOMO_DIR = os.path.join(_BASE_DIR, "bin")


OUTPUT_DIR = os.path.join(_BASE_DIR, "output")


LOG_DIR = os.path.join(_BASE_DIR, "log")  # v4.8 起日志独立目录（JSONL，只保留最新一个文件）


SUBSCRIBE_FILE = os.path.join(_BASE_DIR, "代理.txt")


TCP_PING_CONCURRENCY = 40


HTTP_LATENCY_TIMEOUT = 5


HTTP_DOWNLOAD_TIMEOUT = 30


STREAMING_TEST_TIMEOUT = 8


IP_QUALITY_TIMEOUT = 10


# IP 源请求全局节流（req/min）：ip-api.com 免费版 45 req/min 限流，
# 并行路径多节点同时打主源会 429 → 降级到无风控字段的回退源（ip_type/风险 "--"）。
# 40/min 留余量，跨 worker 共享（v4.26.0）
IP_RATE_LIMIT_PER_MIN = 40


WPS_INTERNATIONAL_URLS = [
    ("google", "https://www.google.com/generate_204"),
    ("youtube", "https://www.youtube.com/"),
    ("bing", "https://www.bing.com/"),
    ("github", "https://github.com/"),
]


WPS_CN_URLS = [
    ("baidu", "https://www.baidu.com/"),
    ("bilibili", "https://www.bilibili.com/"),
    ("qq", "https://www.qq.com/"),
]


DEFAULT_WORKERS = 4


MAX_WORKERS = 8


TCP_PROBE_CONCURRENCY = 4


TCP_PROBE_TIMEOUT = 5


SPEED_WINDOW_DEFAULT_SECONDS = 8


SPEED_WINDOW_FAST_SECONDS = 5


MIN_SPEED_BYTES = 256 * 1024


DOWNLOAD_CONNS = 4


SLOW_ABORT_SECONDS = 3


SLOW_ABORT_BYTES = 64 * 1024


SPEED_TEST_URLS = [
    "https://speed.cloudflare.com/__down?bytes=20000000",  # Cloudflare 20MB（主）
    "https://cachefly.cachefly.net/100mb.test",            # CacheFly 100MB（备）
    "https://proof.ovh.net/files/100Mb.dat",               # OVH 100MB（备）
]


YOUTUBE_VIDEO_IDS = ["LXb3EKWsInQ", "aqz-KE-bpKQ", "9bZkp7q19f0"]


YOUTUBE_SOURCE_ENABLED = False


IP_CHECK_INTERVAL = 1.0


UDP_TYPES = {"hysteria", "hysteria2", "tuic", "juicity", "wireguard"}


# 历史配色表（保留供外部引用；当前报告柱状图实际使用 report._bar_color：
# v4.25.0 起 = SSRSpeedN v1.04 origin 色表同款：≤4MB/s→浅绿、4-8→黄、8-16→橙、
# 16-24→红、24-32→紫、32-40→蓝、40MB/s+→深蓝，见 CLAUDE.md 描述）
SPEED_COLORS = [
    (0, (255, 255, 255)),        # 0       → 白色
    (64 * 1024, (102, 255, 102)),  # 64KB/s  → 浅绿
    (512 * 1024, (255, 255, 102)), # 512KB/s → 黄色
    (4 * 1024 * 1024, (255, 178, 102)),  # 4MB/s → 橙色
    (16 * 1024 * 1024, (255, 102, 102)), # 16MB/s → 红色
    (24 * 1024 * 1024, (226, 140, 255)), # 24MB/s → 紫色
    (32 * 1024 * 1024, (102, 204, 255)), # 32MB/s → 蓝色
    (40 * 1024 * 1024, (102, 102, 255)), # 40MB/s+→ 深蓝
]


# ---- PNG 报告版式色（v4.32.0，新视觉方案） ----
REPORT_PAGE_BG     = (255, 255, 255)   # #FFFFFF 数据区纯白（MiaoKo，替换原画布 #EBEBEB）
REPORT_TITLE_BG    = (235, 235, 235)   # #EBEBEB 标题栏/页脚浅灰（MiaoKo）
REPORT_HEADER_BG   = (255, 255, 255)   # #FFFFFF 表头纯白（MiaoKo，替换原灰底 #E4E4E4）
REPORT_FOOTER_BG   = (235, 235, 235)   # #EBEBEB 页脚浅灰（MiaoKo）
REPORT_GRID        = (230, 230, 230)   # #E6E6E6 列间淡竖线（MiaoKo，替换原白网格）
REPORT_OUTER       = (200, 200, 200)   # #C8C8C8 浅灰细外框（MiaoKo，替换原深灰 #A0A0A0）
REPORT_BLACK       = (0, 0, 0)         # 所有文字（直绘不描边）
REPORT_ZEBRA       = ((255, 255, 255), (255, 255, 255))   # MiaoKo：数据行纯白（无斑马，替换原双档）
REPORT_SPECIAL_BG  = (233, 233, 233)   # #E9E9E9 特殊态灰块（超时/--/UDP/代理可达，MiaoKo 淡化）（超时/--/UDP/代理可达）

# ---- 延迟梯度（延迟RTT / HTTP延迟 / 网页均耗 共用，快=绿→慢=红，帧间线性插值）----
LATENCY_RAMP = [(0, (77, 208, 111)), (100, (77, 208, 111)), (250, (139, 195, 74)),
                (500, (174, 213, 129)), (900, (245, 155, 0)), (1500, (255, 112, 0))]
# MiaoKo：快=亮绿 #4DD06F → 中=黄绿 #8BC34A → 慢=深橙 #FF7000（替换原红系 #1E9650→#D2321E）

# ---- 速度色板（平均/最高/每秒速度段 共用，慢=红→快=绿）----
SPEED_RAMP_R2G = [(0, (180, 40, 35)), (4, (180, 40, 35)), (8, (205, 65, 50)),
                  (16, (215, 115, 50)), (24, (205, 160, 45)), (32, (140, 160, 50)),
                  (40, (70, 140, 80)), (50, (40, 115, 65))]
SPEED_NORM = [(0, (180, 40, 35)), (1 / 6, (205, 65, 50)), (2 / 6, (215, 115, 50)),
              (3 / 6, (205, 160, 45)), (4 / 6, (140, 160, 50)), (5 / 6, (70, 140, 80)),
              (1, (40, 115, 65))]      # 对数映射用归一化色序 p∈[0,1]（旧红绿，保留兼容）
SPEED_ADAPT_MAX = 8.0                 # 报表最大速度 < 8MB/s → 全表低速线性铺满（旧逻辑，保留兼容）

# ---- MiaoKo 蓝绿冷色系速度色板（替换 v4.32 红绿；report._speed_color 改用本板）----
# 慢=浅绿 → 中=蓝 → 快=深蓝；高速区平缓（整体色差小），只有极慢才落向浅绿
MIAO_SPEED = [
    (0.0, (185, 230, 125)),   # 0   浅绿（极慢 #B9E67D）
    (0.12, (143, 208, 200)),  # 浅蓝绿 #8FD0C8
    (0.25, (77, 184, 240)),   # 浅蓝 #4DB8F0
    (0.4, (30, 150, 245)),    # 蓝 #1E96F5
    (0.6, (20, 135, 242)),    # 蓝（开始平缓）
    (0.8, (16, 128, 240)),    # 深蓝（平缓）
    (1.0, (13, 122, 237)),    # 快 深蓝 #0D9AF2
]
MIAO_SPEED_REF = 25.0          # 速度评分参考上限 MB/s（log2 映射，>25MB/s 即最蓝）

# ---- 流媒体状态色 ----
STREAMING_STATUS_COLORS = {
    "ok": (185, 230, 125),       # 解锁/可用 → 浅绿 #B9E67D（MiaoKo 柔和绿）
    "pending": (224, 189, 84),   # 待解锁/自制 → 柔和黄 #E0BD54
    "fail": (238, 106, 117),     # 失败/封锁/连接失败 → 柔粉 #EE6A75
    "na": (176, 176, 176),       # N/A/查询失败 → 中灰 #B0B0B0
    "unknown": (150, 152, 158),  # 未知 → 灰 #96989E
    "skip": (158, 158, 158),     # 跳过(节点不可达) → 深灰 #9E9E9E
}
# 未测（"--"/空）→ 斑马底 + 黑字，不填色

# ---- IP 质量 / 复用 ----
IP_TYPE_COLORS = {
    "residential": (185, 230, 125),   # 家宽/移动 → 浅绿 #B9E67D（MiaoKo 与流媒体统一）
    "datacenter": (224, 189, 84),     # 商宽/机房 → 柔和黄 #E0BD54
    "proxy": (238, 106, 117),         # 代理/VPN/Tor → 柔粉 #EE6A75
}
# IP风险：低 → ok 绿；中 → pending 黄；高 → fail 红（复用 STREAMING_STATUS_COLORS 的 ok/pending/fail）
REUSE_COLORS = {
    "full": (200, 60, 55),            # 完全复用 → 深红（最重）
    "relay": (205, 150, 15),          # 中转复用 → 深黄（中等）
    "landing": (30, 140, 175),        # 落地复用 → 深青（最轻）
}


# 流媒体服务表。检测路由只消费 id/url/name（streaming.py 按 id 查 STREAMING_CHECKERS、
# 其余走通用探测）；"type" 字段为历史保留字段（v4.38.0 注明），当前无代码消费，勿依赖。
CORE_STREAMING_SERVICES = [
    {"id": "youtube",   "name": "YouTube",    "url": "https://www.youtube.com",         "type": "youtube"},
    {"id": "netflix",   "name": "Netflix",    "url": "https://www.netflix.com",         "type": "netflix"},
    {"id": "disney",    "name": "Disney+",    "url": "https://www.disneyplus.com",      "type": "disney"},
    {"id": "chatgpt",   "name": "OpenAI",     "url": "https://chat.openai.com",         "type": "chatgpt"},
]


STANDARD_STREAMING_SERVICES = CORE_STREAMING_SERVICES + [
    {"id": "abema",     "name": "AbemaTV",    "url": "https://abema.tv",                "type": "abema"},
    {"id": "bilibili_tw", "name": "B站港澳台", "url": "https://www.bilibili.com",        "type": "bilibili_tw"},
    {"id": "dazn",      "name": "Dazn",       "url": "https://www.dazn.com",            "type": "dazn"},
    {"id": "hbomax",    "name": "HboMax",     "url": "https://www.hbomax.com",          "type": "hbomax"},
]


FULL_STREAMING_SERVICES = STANDARD_STREAMING_SERVICES + [
    {"id": "tiktok",    "name": "TikTok",     "url": "https://www.tiktok.com",          "type": "tiktok"},
    {"id": "spotify",   "name": "Spotify",    "url": "https://www.spotify.com",         "type": "spotify"},
    {"id": "primevideo","name": "PrimeVideo", "url": "https://www.primevideo.com",      "type": "primevideo"},
    {"id": "max",       "name": "Max(HBO)",   "url": "https://www.max.com",             "type": "max"},
    {"id": "appletv",   "name": "AppleTV",    "url": "https://tv.apple.com",            "type": "appletv"},
    {"id": "iqiyi",     "name": "iQiyi",      "url": "https://www.iq.com",              "type": "iqiyi"},
    {"id": "twitter",   "name": "Twitter(X)", "url": "https://x.com",                   "type": "twitter"},
    {"id": "instagram", "name": "Instagram",  "url": "https://www.instagram.com",       "type": "instagram"},
    {"id": "telegram",  "name": "Telegram",   "url": "https://web.telegram.org",         "type": "telegram"},
    {"id": "discord",   "name": "Discord",    "url": "https://discord.com",              "type": "discord"},
    {"id": "twitch",    "name": "Twitch",     "url": "https://www.twitch.tv",           "type": "twitch"},
    {"id": "soundcloud","name": "SoundCloud", "url": "https://soundcloud.com",          "type": "soundcloud"},
    {"id": "crunchyroll","name": "Crunchyroll","url": "https://www.crunchyroll.com",     "type": "crunchyroll"},
    {"id": "steam",     "name": "Steam",      "url": "https://store.steampowered.com",  "type": "steam"},
    {"id": "epicgames", "name": "EpicGames",  "url": "https://store.epicgames.com",     "type": "epicgames"},
    {"id": "reddit",    "name": "Reddit",     "url": "https://www.reddit.com",          "type": "reddit"},
    {"id": "wikipedia", "name": "Wikipedia",  "url": "https://www.wikipedia.org",       "type": "wikipedia"},
    {"id": "projectsekai","name": "ProjectSekai","url": "https://pjsekai.sega.jp",      "type": "projectsekai"},
    # AI 服务（chatgpt 已在 CORE 中，这里只加额外的）
    {"id": "claude",     "name": "Claude",     "url": "https://claude.ai",               "type": "claude"},
    {"id": "gemini",     "name": "Gemini",     "url": "https://gemini.google.com",        "type": "gemini"},
    {"id": "perplexity", "name": "Perplexity", "url": "https://www.perplexity.ai",        "type": "perplexity"},
    {"id": "deepseek",   "name": "DeepSeek",   "url": "https://chat.deepseek.com",        "type": "deepseek"},
    {"id": "moonshot",   "name": "Kimi",       "url": "https://kimi.moonshot.cn",         "type": "moonshot"},
    {"id": "grok",       "name": "Grok",       "url": "https://grok.com",                  "type": "grok"},
    {"id": "doubao",     "name": "豆包",       "url": "https://www.doubao.com",           "type": "doubao"},
]


AI_STREAMING_SERVICES = [
    {"id": "chatgpt",    "name": "OpenAI",     "url": "https://chat.openai.com",          "type": "chatgpt"},
    {"id": "claude",     "name": "Claude",     "url": "https://claude.ai",               "type": "claude"},
    {"id": "gemini",     "name": "Gemini",     "url": "https://gemini.google.com",        "type": "gemini"},
    {"id": "perplexity", "name": "Perplexity", "url": "https://www.perplexity.ai",        "type": "perplexity"},
    {"id": "deepseek",   "name": "DeepSeek",   "url": "https://chat.deepseek.com",        "type": "deepseek"},
    {"id": "moonshot",   "name": "Moonshot",   "url": "https://kimi.moonshot.cn",         "type": "moonshot"},
    {"id": "grok",       "name": "Grok",       "url": "https://grok.com",                  "type": "grok"},
    {"id": "doubao",     "name": "豆包",       "url": "https://www.doubao.com",           "type": "doubao"},
]


# 简单测速分组（当前菜单1 不跑流媒体，此列表保留供外部引用/未来接入，勿删接口）
SIMPLE_STREAMING_SERVICES = [
    {"id": "youtube",   "name": "YouTube",    "url": "https://www.youtube.com",         "type": "youtube"},
    {"id": "netflix",   "name": "Netflix",    "url": "https://www.netflix.com",         "type": "netflix"},
    {"id": "disney",    "name": "Disney+",    "url": "https://www.disneyplus.com",      "type": "disney"},
]


_COMMON_IDS = ["youtube", "netflix", "disney", "bilibili_tw",
               "chatgpt", "tiktok", "primevideo", "max"]


COMMON_STREAMING_SERVICES = [
    s for i in _COMMON_IDS
    for s in [next((x for x in FULL_STREAMING_SERVICES if x["id"] == i), None)]
    if s is not None  # 兜底：id 缺失时跳过而非导入期抛 StopIteration
]


# v4.30.0：快速检测的 4 核心流媒体（均有专用检测器，与 COMMON 交集=纯解锁平台）
QUICK_STREAMING = [
    s for i in QUICK_STREAMING_IDS
    for s in [next((x for x in FULL_STREAMING_SERVICES if x["id"] == i), None)]
    if s is not None
]


_STREAM_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

__all__ = ['VERSION', 'MIHOMO_REPO', '_SCRIPT_DIR', '_BASE_DIR', 'MIHOMO_DIR', 'OUTPUT_DIR', 'LOG_DIR', 'SUBSCRIBE_FILE', 'TCP_PING_CONCURRENCY', 'HTTP_LATENCY_TIMEOUT', 'HTTP_DOWNLOAD_TIMEOUT', 'STREAMING_TEST_TIMEOUT', 'IP_QUALITY_TIMEOUT', 'IP_RATE_LIMIT_PER_MIN', 'WPS_INTERNATIONAL_URLS', 'WPS_CN_URLS', 'DEFAULT_WORKERS', 'MAX_WORKERS', 'TCP_PROBE_CONCURRENCY', 'TCP_PROBE_TIMEOUT', 'SPEED_WINDOW_DEFAULT_SECONDS', 'SPEED_WINDOW_FAST_SECONDS', 'MIN_SPEED_BYTES', 'DOWNLOAD_CONNS', 'SLOW_ABORT_SECONDS', 'SLOW_ABORT_BYTES', 'SPEED_TEST_URLS', 'YOUTUBE_VIDEO_IDS', 'YOUTUBE_SOURCE_ENABLED', 'IP_CHECK_INTERVAL', 'UDP_TYPES', 'SPEED_COLORS', 'CORE_STREAMING_SERVICES', 'STANDARD_STREAMING_SERVICES', 'FULL_STREAMING_SERVICES', 'AI_STREAMING_SERVICES', 'SIMPLE_STREAMING_SERVICES', '_COMMON_IDS', 'COMMON_STREAMING_SERVICES', 'QUICK_DOWNLOAD_URL', 'QUICK_WINDOW', 'QUICK_WORKERS', 'QUICK_TCP_TIMEOUT', 'QUICK_STREAMING_IDS', 'QUICK_STREAMING', '_STREAM_UA', 'SILENT_RUNS', 'SILENT_DAYS', 'EVIDENCE_MAX', 'RUNS_MAX', 'STABILITY_APPEAR_RATIO', 'STABILITY_SIGMA', 'NEW_FACE_MIN_EVIDENCE', 'KEEP_REPORTS_DEFAULT', 'KEEP_LOGS_DAYS_DEFAULT', 'REPORT_PAGE_BG', 'REPORT_TITLE_BG', 'REPORT_HEADER_BG', 'REPORT_FOOTER_BG', 'REPORT_GRID', 'REPORT_OUTER', 'REPORT_BLACK', 'REPORT_ZEBRA', 'REPORT_SPECIAL_BG', 'LATENCY_RAMP', 'SPEED_RAMP_R2G', 'SPEED_NORM', 'SPEED_ADAPT_MAX', 'MIAO_SPEED', 'MIAO_SPEED_REF', 'STREAMING_STATUS_COLORS', 'IP_TYPE_COLORS', 'REUSE_COLORS']
