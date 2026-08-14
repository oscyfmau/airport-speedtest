#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机场测速工具 v4.8
订阅解析 → TCP Ping → HTTP测速 → 流媒体解锁 → IP风控 → PNG报告
"""

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

import aiohttp
import requests as _requests
import yaml
from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm

# 可选依赖
HAS_CLOUDSCRAPER = False
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    pass

HAS_YTDLP = False
try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════
#  日志
# ═══════════════════════════════════════════════════════════════

logger = logging.getLogger("speed_test")
_LOG_FILE = ""
_JSONL_HANDLER = None


def _cleanup_stale_configs():
    """清理历史运行（异常退出）残留的临时配置文件"""
    try:
        tmp = tempfile.gettempdir()
        for f in os.listdir(tmp):
            if (f.startswith("mihomo_") or f.startswith("mihomo_worker_")) and f.endswith(".yaml"):
                try:
                    os.remove(os.path.join(tmp, f))
                except OSError:
                    pass
    except Exception:
        pass


def setup_logging() -> str:
    """初始化日志：控制台 INFO（文本）+ 文件 JSONL（log/测速日志_*.jsonl），返回日志文件路径"""
    global _LOG_FILE, _JSONL_HANDLER
    _cleanup_stale_configs()
    logger.setLevel(logging.DEBUG)

    if logger.handlers:  # 已初始化（如菜单多次运行）：移除旧控制台 handler，避免重复输出
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(_ConsoleFormatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)

    _install_excepthook()
    return new_run_log()


def new_run_log() -> str:
    """每次测试运行开始时新建 JSONL 日志文件（菜单多次运行不混写同一文件）"""
    global _LOG_FILE, _JSONL_HANDLER
    if _JSONL_HANDLER is not None:
        logger.removeHandler(_JSONL_HANDLER)
        _JSONL_HANDLER.close()
    os.makedirs(LOG_DIR, exist_ok=True)
    _LOG_FILE = os.path.join(LOG_DIR, time.strftime("测速日志_%Y%m%d_%H%M%S.jsonl"))
    _JSONL_HANDLER = JsonlFileHandler(_LOG_FILE)
    logger.addHandler(_JSONL_HANDLER)
    return _LOG_FILE


class JsonlFileHandler(logging.Handler):
    """JSONL 文件日志：每行一个 JSON 对象，逐条 flush（强杀/关窗口也不丢已写内容）"""

    def __init__(self, path: str, level=logging.DEBUG):
        super().__init__(level)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "event": getattr(record, "event", "") or "",
                "msg": record.getMessage(),
            }
            data = getattr(record, "data", None)
            if data is not None:
                entry["data"] = data
            if record.exc_info:
                entry["exc"] = "".join(traceback.format_exception(*record.exc_info)).strip()
            self._fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
        super().close()


def _ev(event: str, data=None) -> dict:
    """构造 logger extra：结构化事件名 + 数据（JSONL 用，控制台忽略）"""
    return {"event": event, "data": data}


def _pkg_version(name: str) -> str:
    """读取已安装包版本（失败返回 ?）"""
    try:
        import importlib.metadata as _im
        return _im.version(name)
    except Exception:
        return "?"


def _install_excepthook() -> None:
    """全局未捕获异常兜底：完整 traceback 写入 JSONL（乱操作也不丢现场）"""
    def _hook(tp, val, tb):
        text = "".join(traceback.format_exception(tp, val, tb)).strip()
        try:
            logger.critical("未捕获异常: %s", text,
                            extra=_ev("uncaught_exception", {"traceback": text}))
        except Exception:
            pass
        sys.__excepthook__(tp, val, tb)
    sys.excepthook = _hook


def _mask_url(url: str) -> str:
    """遮蔽 URL 中敏感参数的值（token/key/secret 等），用于打印与日志"""
    if "?" not in url:
        return url
    base, qs = url.split("?", 1)
    parts = []
    for p in qs.split("&"):
        if "=" in p:
            k, v = p.split("=", 1)
            if k.lower() in ("token", "password", "passwd", "key", "secret", "auth"):
                v = "***"
            parts.append(f"{k}={v}")
        else:
            parts.append(p)
    return f"{base}?{'&'.join(parts)}"


_FLAG_PAIR_RE = re.compile(r"([\U0001F1E6-\U0001F1FF]){2}")


def _flag_to_text(s: str) -> str:
    """控制台安全化显示名：国旗 emoji 对 → [国家代码]，其余 astral-plane 字符删除。

    仅用于控制台与进度条显示；节点原名、文件日志、PNG 报告、JSON 均不变。
    """
    if not s:
        return s

    def _pair(m):
        a, b = m.group(0)
        return f"[{chr(ord(a) - 0x1F1E6 + 65)}{chr(ord(b) - 0x1F1E6 + 65)}]"

    new = _FLAG_PAIR_RE.sub(_pair, s)
    new = re.sub(r"[\U00010000-\U0010FFFF]", "", new)
    return new.strip() if new != s else s


class _ConsoleFormatter(logging.Formatter):
    """仅控制台格式化器：整行套用 _flag_to_text（国旗 emoji 转 [XX]）。

    文件日志用普通 Formatter，保留原始节点名。
    """

    def format(self, record):
        return _flag_to_text(super().format(record))


# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

VERSION = "v4.8"
MIHOMO_REPO = "MetaCubeX/mihomo"

# 项目根目录：脚本在子目录(core/src)中时取上级，否则取脚本所在目录
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SCRIPT_DIR) if os.path.basename(_SCRIPT_DIR) in ("core", "src") else _SCRIPT_DIR

MIHOMO_DIR = os.path.join(_BASE_DIR, "bin")
OUTPUT_DIR = os.path.join(_BASE_DIR, "output")
LOG_DIR = os.path.join(_BASE_DIR, "log")  # v4.8 起日志独立目录（JSONL）
SUBSCRIBE_FILE = os.path.join(_BASE_DIR, "代理.txt")

# TCP Ping 并发数
TCP_PING_CONCURRENCY = 40
# HTTP 测试并发数（通过 mihomo，实际串行切换）
HTTP_LATENCY_TIMEOUT = 5
HTTP_DOWNLOAD_TIMEOUT = 30
STREAMING_TEST_TIMEOUT = 8
IP_QUALITY_TIMEOUT = 10

# 并行 mihomo 工作进程数（--workers 可覆盖；仅控制流媒体/IP 阶段并行度，测速恒串行）
DEFAULT_WORKERS = 4
MAX_WORKERS = 8

# TCP 来源B（mihomo 隧道探测）并发数上限
TCP_PROBE_CONCURRENCY = 4
# 隧道探测超时（秒）
TCP_PROBE_TIMEOUT = 5

# 测速窗口（秒）：每秒一个槽位；--fast 时降为 5
SPEED_WINDOW_DEFAULT_SECONDS = 8
SPEED_WINDOW_FAST_SECONDS = 5
SPEED_WINDOW_SECONDS = SPEED_WINDOW_DEFAULT_SECONDS  # 运行时全局（--fast 会改写）

# 测速最小有效下载量（字节）：低于此值视为拦截页/空响应，不记速度
MIN_SPEED_BYTES = 256 * 1024

# 单节点并发下载连接数（多线程下载，轮流取多个源）
DOWNLOAD_CONNS = 4

# 慢节点提前终止：窗口内前 N 秒累计下载低于该字节数 → 判定速度过低
SLOW_ABORT_SECONDS = 3
SLOW_ABORT_BYTES = 64 * 1024

# 速度测试文件（多源回退：主源失败自动换下一个）
SPEED_TEST_URLS = [
    "https://speed.cloudflare.com/__down?bytes=20000000",  # Cloudflare 20MB（主）
    "https://cachefly.cachefly.net/100mb.test",            # CacheFly 100MB（备）
    "https://proof.ovh.net/files/100Mb.dat",               # OVH 100MB（备）
]

# 油管测速源：innertube player API 解析 googlevideo 直链（签名 URL 约 6 小时有效）
YOUTUBE_VIDEO_IDS = ["LXb3EKWsInQ", "aqz-KE-bpKQ", "9bZkp7q19f0"]
_YOUTUBE_DL_URL = None  # 运行时缓存：解析成功后追加到测速源列表


class _YtDlpNullLogger:
    """吞掉 yt-dlp 全部输出（直连失败属预期，由本模块 logger 记录）"""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def resolve_youtube_download_url(timeout: int = 15, proxy: str = None) -> str:
    """解析油管视频直链（googlevideo），失败返回空串。每次运行开始时调用一次。

    依赖 yt-dlp（处理签名解密与 PO token）；格式优先级 137/136/22/18/best；
    视频不可用或解析失败时尝试下一个视频 ID；总耗时上限 30 秒。
    proxy 为空时走本机直连（尊重环境代理变量），否则经指定 HTTP 代理（节点隧道）。
    """
    global _YOUTUBE_DL_URL
    if _YOUTUBE_DL_URL:
        return _YOUTUBE_DL_URL
    if not HAS_YTDLP:
        logger.warning("未安装 yt-dlp，跳过油管测速源（pip install yt-dlp）")
        return ""
    opts = {
        "format": "137/136/22/18/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": timeout,
        "logger": _YtDlpNullLogger(),
    }
    if proxy:
        opts["proxy"] = proxy
    t_start = time.monotonic()
    for vid in YOUTUBE_VIDEO_IDS:
        if time.monotonic() - t_start > 30:
            break
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(vid, download=False)
                formats = (info or {}).get("formats") or []
                selected = (info or {}).get("format_id")
                # 优先取选中格式的直链，否则取第一个带 url 的格式
                for f in formats:
                    if selected and f.get("format_id") == selected and f.get("url"):
                        _YOUTUBE_DL_URL = f["url"]
                        return _YOUTUBE_DL_URL
                for f in formats:
                    if f.get("url"):
                        _YOUTUBE_DL_URL = f["url"]
                        return _YOUTUBE_DL_URL
        except Exception as e:
            logger.debug(
                "yt-dlp 解析失败 videoId=%s: %s", vid, e,
                extra=_ev("yt_source_attempt",
                          {"video_id": vid, "proxy": bool(proxy), "error": str(e)[:300]}))
            continue
    return ""

# IP 质量检测最小间隔（秒）：免费 API 有限额，并行模式下全局节流防 429
IP_CHECK_INTERVAL = 1.0

# UDP/QUIC 系协议：无 TCP 握手，跳过直连 TCP Ping（可达性由 mihomo 隧道探测判定）
UDP_TYPES = {"hysteria", "hysteria2", "tuic", "juicity", "wireguard"}

# StairSpeedTest 风格速度颜色阈值（单位：字节/秒）
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

CORE_STREAMING_SERVICES = [
    {"id": "youtube",   "name": "YouTube",    "url": "https://www.youtube.com",         "type": "youtube"},
    {"id": "netflix",   "name": "Netflix",    "url": "https://www.netflix.com",         "type": "netflix"},
    {"id": "disney",    "name": "Disney+",    "url": "https://www.disneyplus.com",      "type": "disney"},
    {"id": "chatgpt",   "name": "OpenAI",     "url": "https://chat.openai.com",         "type": "chatgpt"},
]

STANDARD_STREAMING_SERVICES = CORE_STREAMING_SERVICES + [
    {"id": "abema",     "name": "AbemaTV",    "url": "https://abema.tv",                "type": "abema"},
    {"id": "bilibili",  "name": "BiliBili",   "url": "https://www.bilibili.com",        "type": "bilibili"},
    {"id": "bilibili_tw", "name": "B站港澳台", "url": "https://www.bilibili.com",        "type": "bilibili_tw"},
    {"id": "dazn",      "name": "Dazn",       "url": "https://www.dazn.com",            "type": "dazn"},
    {"id": "hbomax",    "name": "HboMax",     "url": "https://www.hbomax.com",          "type": "hbomax"},
]

FULL_STREAMING_SERVICES = STANDARD_STREAMING_SERVICES + [
    {"id": "tiktok",    "name": "TikTok",     "url": "https://www.tiktok.com",          "type": "tiktok"},
    {"id": "spotify",   "name": "Spotify",    "url": "https://www.spotify.com",         "type": "spotify"},
    {"id": "primevideo","name": "PrimeVideo", "url": "https://www.primevideo.com",      "type": "prime"},
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

SIMPLE_STREAMING_SERVICES = [
    {"id": "youtube",   "name": "YouTube",    "url": "https://www.youtube.com",         "type": "youtube"},
    {"id": "bilibili",  "name": "BiliBili",   "url": "https://www.bilibili.com",        "type": "bilibili"},
    {"id": "netflix",   "name": "Netflix",    "url": "https://www.netflix.com",         "type": "netflix"},
    {"id": "disney",    "name": "Disney+",    "url": "https://www.disneyplus.com",      "type": "disney"},
]

# 标准测试（菜单2）用：常见高频平台（含 B站港澳台）
# 从 FULL 列表按 id 取，保持单一数据源
_COMMON_IDS = ["youtube", "netflix", "disney", "bilibili", "bilibili_tw",
               "chatgpt", "tiktok", "primevideo", "max"]
COMMON_STREAMING_SERVICES = [
    next(s for s in FULL_STREAMING_SERVICES if s["id"] == i) for i in _COMMON_IDS
]


# ═══════════════════════════════════════════════════════════════
#  数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProxyNode:
    name: str
    type: str          # ss/vmess/trojan/...
    server: str
    port: int
    extra: dict = field(default_factory=dict)

    def to_clash_proxy(self) -> dict:
        """转换为 Clash YAML 代理配置"""
        proxy = {"name": self.name, "type": self.type, "server": self.server, "port": self.port}
        proxy.update(self.extra)
        return proxy


@dataclass
class TestResult:
    node: ProxyNode
    tcp_ping: Optional[float] = None
    tcp_probe: Optional[bool] = None   # 来源B：mihomo 隧道探测（None=未探测）
    http_latency: Optional[float] = None
    speed: Optional[float] = None       # MB/s 平均速度
    max_speed: Optional[float] = None   # MB/s 峰值速度
    speed_per_sec: list = field(default_factory=list)  # 每秒速度数组
    streaming: dict = field(default_factory=dict)
    ip_info: dict = field(default_factory=dict)
    error: Optional[str] = None


def is_udp_node(node: ProxyNode) -> bool:
    """判定节点是否走 UDP 传输：UDP 系协议，或 vmess/vless 的 kcp/quic 传输层"""
    return node.type in UDP_TYPES or node.extra.get("network") in ("kcp", "quic")


def _no_verify_ssl() -> ssl.SSLContext:
    """构建跳过证书校验的 SSL 上下文（本机经 mihomo 隧道访问目标站用）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _udp_type_text(node: ProxyNode) -> str:
    """报告"UDP类型"列的传输层文本"""
    net = node.extra.get("network")
    if net == "kcp":
        return "KCP"
    if net == "quic":
        return "QUIC"
    if node.type in ("hysteria", "hysteria2", "tuic", "juicity"):
        return "QUIC"
    if node.type == "wireguard":
        return "UDP"
    return "TCP"


# ═══════════════════════════════════════════════════════════════
#  订阅解析器
# ═══════════════════════════════════════════════════════════════

def _remove_prefix(s: str, prefix: str) -> str:
    """移除字符串前缀（兼容 Python 3.8+）"""
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def b64decode_pad(s: str) -> bytes:
    """Base64 解码，自动处理 padding"""
    s = s.strip()
    # 处理 URL-safe base64
    s = s.replace('-', '+').replace('_', '/')
    padding = (4 - len(s) % 4) % 4
    if padding != 4:
        s += '=' * padding
    return base64.b64decode(s)


def parse_vmess(uri: str) -> Optional[ProxyNode]:
    """解析 vmess:// Base64 JSON"""
    try:
        raw = _remove_prefix(uri, "vmess://")
        data = json.loads(b64decode_pad(raw))
        extra = {
            "uuid": data.get("id", ""),
            "alterId": data.get("aid", 0),
            "alter-id": data.get("aid", 0),
            "cipher": data.get("scy", "auto") or "auto",
        }
        if data.get("tls"):
            extra["tls"] = True
        net = data.get("net", "")
        if net == "ws":
            extra["network"] = "ws"
            if data.get("path"):
                extra["ws-path"] = data["path"]
            if data.get("host"):
                extra["ws-headers"] = {"Host": data["host"]}
        elif net in ("tcp", "kcp", "http", "grpc"):
            extra["network"] = net
        # VMess "aid" → alterId / alter-id（兼容新旧版）
        return ProxyNode(
            name=data.get("ps", data.get("add", "")),
            type="vmess",
            server=data.get("add", ""),
            port=int(data.get("port", 0)),
            extra=extra,
        )
    except Exception:
        return None


def _parse_userhost_port(uri: str):
    """统一提取 user/host/port/fragment，正确处理 IPv6"""
    parsed = urlparse(uri)
    user = ""
    if parsed.username:
        user = parsed.username
    elif "@" in parsed.netloc:
        user = parsed.netloc.split("@", 1)[0]
    server = parsed.hostname or ""
    port = parsed.port or 443
    params = parse_qs(parsed.query)
    name = unquote(parsed.fragment) if parsed.fragment else server
    return user, server, port, params, name, parsed


def parse_vless(uri: str) -> Optional[ProxyNode]:
    """解析 vless:// UUID@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"uuid": user, "cipher": "none"}
        if params.get("security", [""])[0] == "reality":
            extra["reality"] = True
            # reality-opts：从 query 参数提取 pbk/sid 等
            opts = {}
            if params.get("pbk"):
                opts["public-key"] = params["pbk"][0]
            if params.get("sid"):
                opts["short-id"] = params["sid"][0]
            if params.get("spx"):
                opts["spiderX"] = params["spx"][0]
            if opts:
                extra["reality-opts"] = opts
        if params.get("flow", [""])[0]:
            extra["flow"] = params["flow"][0]
        extra["network"] = params.get("type", ["tcp"])[0]
        if extra["network"] == "ws":
            if params.get("path"):
                extra["ws-path"] = params["path"][0]
            if params.get("host"):
                extra["ws-headers"] = {"Host": params["host"][0]}
        return ProxyNode(name=name, type="vless", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_trojan(uri: str) -> Optional[ProxyNode]:
    """解析 trojan:// pass@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("allowInsecure"):
            extra["skip-cert-verify"] = params["allowInsecure"][0].lower() == "true"
        return ProxyNode(name=name, type="trojan", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_ss(uri: str) -> Optional[ProxyNode]:
    """解析 ss:// SIP002 格式"""
    try:
        parsed = urlparse(uri)
        raw = parsed.netloc or parsed.path
        name = unquote(parsed.fragment) if parsed.fragment else ""
        # 尝试 SIP002 标准: ss://base64(method:password)@host:port
        if "@" in raw:
            # method:password@host:port 格式
            user_info, host_port = raw.split("@", 1)
            # user_info 可能是 base64 编码
            try:
                decoded = b64decode_pad(user_info).decode()
                if ":" in decoded:
                    method, password = decoded.split(":", 1)
                else:
                    method, password = "aes-256-gcm", decoded
            except Exception:
                # 明文 userinfo（非 base64）：method:password 直接拆分
                if ":" in user_info:
                    method, password = user_info.split(":", 1)
                else:
                    method, password = "aes-256-gcm", user_info
            hp = host_port.rsplit(":", 1)
            server = hp[0].strip("[]")  # IPv6 剥离方括号
            port = int(hp[1]) if len(hp) > 1 else 443
        else:
            # 纯 base64: ss://base64(method:password@host:port)
            decoded = b64decode_pad(raw).decode()
            # method:password@host:port
            user_info, host_port = decoded.split("@", 1)
            method, password = user_info.split(":", 1)
            hp = host_port.rsplit(":", 1)
            server = hp[0].strip("[]")  # IPv6 剥离方括号
            port = int(hp[1]) if len(hp) > 1 else 443
        # SIP002 插件参数
        params = parse_qs(parsed.query)
        extra = {"cipher": method, "password": password}
        if params.get("plugin"):
            extra["plugin"] = params["plugin"][0]
        node_name = name or server
        return ProxyNode(name=node_name, type="ss", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_ssr(uri: str) -> Optional[ProxyNode]:
    """解析 ssr:// Base64 编码"""
    try:
        raw = _remove_prefix(uri, "ssr://")
        decoded = b64decode_pad(raw).decode()
        # 格式: server:port:protocol:method:obfs:base64pass/?params
        parts = decoded.split("/?", 1)
        main = parts[0]
        # SSR 格式：server:port:protocol:method:obfs:password_base64
        # IPv6 地址可能含冒号，取最后5段
        main_parts = main.split(":")
        if len(main_parts) < 6:
            return None
        server = ":".join(main_parts[:-5]).strip("[]")  # IPv6 剥离方括号
        port = main_parts[-5]
        protocol = main_parts[-4]
        method = main_parts[-3]
        obfs = main_parts[-2]
        b64_pass = main_parts[-1]
        password = b64decode_pad(b64_pass).decode()
        extra = {
            "cipher": method,
            "password": password,
            "protocol": protocol,
            "obfs": obfs,
        }
        node_name = server
        if len(parts) > 1:
            params = parts[1]
            for param in params.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    if k == "obfsparam":
                        extra[k] = b64decode_pad(v).decode()
                    elif k == "group":
                        # SSR group 参数（base64）作为节点友好名
                        try:
                            node_name = b64decode_pad(v).decode() or server
                        except Exception:
                            pass
                    else:
                        extra[k] = v
        return ProxyNode(name=node_name, type="ssr", server=server, port=int(port), extra=extra)
    except Exception:
        return None


def parse_hysteria2(uri: str) -> Optional[ProxyNode]:
    """解析 hysteria2:// pass@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("insecure"):
            extra["skip-cert-verify"] = params["insecure"][0].lower() == "true"
        # obfs（salamander）参数映射
        if params.get("obfs"):
            extra["obfs"] = params["obfs"][0]
            if params.get("obfs-password"):
                extra["obfs-password"] = params["obfs-password"][0]
        return ProxyNode(name=name, type="hysteria2", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_hysteria(uri: str) -> Optional[ProxyNode]:
    """解析 hysteria:// host:port?params#name （旧版）"""
    try:
        _, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {
            "protocol": "udp",
            "up": params.get("up", ["100"])[0],
            "down": params.get("down", ["100"])[0],
        }
        if params.get("auth"):
            extra["auth_str"] = params["auth"][0]
        if params.get("auth_str"):
            extra["auth_str"] = params["auth_str"][0]
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("insecure"):
            extra["skip-cert-verify"] = params["insecure"][0].lower() == "true"
        return ProxyNode(name=name, type="hysteria", server=server, port=port, extra=extra)
    except Exception:
        return None


def _parse_uuid_password(uri: str, type_name: str, allow_insecure: bool) -> Optional[ProxyNode]:
    """解析 UUID/password 型协议（tuic/juicity 共用）"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"uuid": user, "password": params.get("password", [""])[0]}
        if params.get("congestion_control"):
            extra["congestion-controller"] = params["congestion_control"][0]
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if allow_insecure and params.get("insecure"):
            extra["skip-cert-verify"] = params["insecure"][0].lower() == "true"
        return ProxyNode(name=name, type=type_name, server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_tuic(uri: str) -> Optional[ProxyNode]:
    """解析 tuic:// UUID@host:port?params#name"""
    return _parse_uuid_password(uri, "tuic", allow_insecure=True)


def parse_anytls(uri: str) -> Optional[ProxyNode]:
    """解析 anytls:// pass@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("insecure") or params.get("allowInsecure"):
            extra["skip-cert-verify"] = True
        if params.get("fp"):
            extra["client-fingerprint"] = params["fp"][0]
        return ProxyNode(name=name, type="anytls", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_wireguard(uri: str) -> Optional[ProxyNode]:
    """解析 wg:// / wireguard://"""
    try:
        parsed = urlparse(uri)
        extra = {}
        if parsed.username:
            extra["public-key"] = unquote(parsed.username)
        if parsed.password:
            extra["private-key"] = unquote(parsed.password)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname or ""
        params = parse_qs(parsed.query)
        if params.get("address"):
            extra["ip"] = params["address"][0]
        if params.get("dns"):
            extra["dns"] = params["dns"][0]
        if params.get("mtu"):
            extra["mtu"] = int(params["mtu"][0])
        return ProxyNode(name=name, type="wireguard", server=parsed.hostname or "",
                        port=parsed.port or 443, extra=extra)
    except Exception:
        return None


def parse_naive(uri: str) -> Optional[ProxyNode]:
    """解析 naive:// / naiveproxy://"""
    try:
        user, server, port, params, name, parsed = _parse_userhost_port(uri)
        extra = {"username": user}
        if parsed.password:
            extra["password"] = unquote(parsed.password)
        return ProxyNode(name=name, type="naive", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_shadowtls(uri: str) -> Optional[ProxyNode]:
    """解析 shadowtls://"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user, "version": params.get("version", ["3"])[0]}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        return ProxyNode(name=name, type="shadowtls", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_juicity(uri: str) -> Optional[ProxyNode]:
    """解析 juicity://"""
    return _parse_uuid_password(uri, "juicity", allow_insecure=False)


def parse_ssh(uri: str) -> Optional[ProxyNode]:
    """解析 ssh://"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"username": user}
        if params.get("password"):
            extra["password"] = params["password"][0]
        if params.get("private-key"):
            extra["private-key"] = params["private-key"][0]
        return ProxyNode(name=name, type="ssh", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_socks(uri: str) -> Optional[ProxyNode]:
    """解析 socks5:// / socks4://"""
    try:
        parsed = urlparse(uri)
        extra = {}
        if parsed.username:
            extra["username"] = unquote(parsed.username)
        if parsed.password:
            extra["password"] = unquote(parsed.password)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname or ""
        return ProxyNode(
            name=name,
            type="socks5",
            server=parsed.hostname or "",
            port=parsed.port or 1080,
            extra=extra,
        )
    except Exception:
        return None


def parse_http(uri: str) -> Optional[ProxyNode]:
    """解析 http:// / https://"""
    try:
        parsed = urlparse(uri)
        extra = {}
        if parsed.username:
            extra["username"] = unquote(parsed.username)
        if parsed.password:
            extra["password"] = unquote(parsed.password)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname or ""
        return ProxyNode(
            name=name,
            type="http",
            server=parsed.hostname or "",
            port=parsed.port or 8080,
            extra=extra,
        )
    except Exception:
        return None


PARSERS = {
    "vmess://": parse_vmess,
    "vless://": parse_vless,
    "trojan://": parse_trojan,
    "ss://": parse_ss,
    "ssr://": parse_ssr,
    "hysteria2://": parse_hysteria2,
    "hysteria://": parse_hysteria,
    "tuic://": parse_tuic,
    "anytls://": parse_anytls,
    "wg://": parse_wireguard,
    "wireguard://": parse_wireguard,
    "naive://": parse_naive,
    "naiveproxy://": parse_naive,
    "shadowtls://": parse_shadowtls,
    "juicity://": parse_juicity,
    "ssh://": parse_ssh,
    "socks5://": parse_socks,
    "socks4://": parse_socks,
    "http://": parse_http,
    "https://": parse_http,
}

URI_PATTERN = re.compile(r"(vmess|vless|trojan|ss|ssr|hysteria2?|tuic|anytls|wg|wireguard|naive|naiveproxy|shadowtls|juicity|ssh|socks[45]|https?)://")


def detect_and_decode(content: str) -> str:
    """自动检测并解码订阅内容"""
    # 尝试直接判断是否含 URI
    if URI_PATTERN.search(content):
        return content
    # 尝试 Base64 解码
    try:
        decoded = b64decode_pad(content).decode("utf-8", errors="replace")
        if URI_PATTERN.search(decoded):
            return decoded
        # 有些订阅是 base64 的 yaml
        if decoded.strip().startswith("proxies:") or "mixed-port" in decoded:
            return decoded
    except Exception:
        pass
    # 尝试 YAML
    if content.strip().startswith("proxies:") or "mixed-port" in content:
        return content
    return content


def _try_fetch(url: str, ua: str) -> str:
    """用指定 UA 获取订阅内容（绕过系统代理）"""
    scraper = None
    try:
        if HAS_CLOUDSCRAPER:
            scraper = cloudscraper.create_scraper()
            scraper.headers.update({"User-Agent": ua})
            scraper.proxies = {"http": "", "https": ""}
            resp = scraper.get(url, timeout=30)
        else:
            raise ImportError("cloudscraper not installed")
    except Exception as e:
        logger.debug(
            "cloudscraper 失败，回退 requests: %s", e,
            extra=_ev("fetch_fallback", {"url": _mask_url(url), "error": str(e)[:200]}))
        try:
            resp = _requests.get(url, headers={"User-Agent": ua}, timeout=30)
        except Exception as e:
            raise RuntimeError(f"订阅下载失败: {e}") from e
    finally:
        if scraper is not None:
            try:
                scraper.close()
            except Exception:
                pass
    resp.encoding = "utf-8"
    return resp.text


def parse_subscription_url(url: str) -> list[ProxyNode]:
    """从订阅 URL 下载并解析节点列表，自动尝试多个 UA 找到最多节点"""
    # 不同 UA 返回不同内容，优先用能获取最多真实节点的
    user_agents = [
        "curl/8.0",
        "ClashMeta/1.0",
        "v2rayN/6.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    ]

    best_nodes = []

    for ua in user_agents:
        try:
            content = _try_fetch(url, ua)
            # 跳过 Cloudflare 挑战页
            if "Attention Required" in content or "Cloudflare" in content[:300]:
                logger.warning("UA %s 返回 Cloudflare 挑战页，跳过", ua)
                continue
            nodes = parse_subscription_content(content)
            if len(nodes) > len(best_nodes):
                best_nodes = nodes
        except Exception as e:
            logger.warning("UA %s 拉取订阅失败: %s", ua, e)
            continue

    if not best_nodes and user_agents:
        # 全部失败，最后再用 cloudscraper 试一次
        scraper = None
        try:
            if HAS_CLOUDSCRAPER:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(url, timeout=30)
            else:
                raise ImportError("cloudscraper not installed")
            resp.encoding = "utf-8"
            best_nodes = parse_subscription_content(resp.text)
        except Exception as e:
            logger.warning("cloudscraper 拉取订阅失败: %s", e)
        finally:
            if scraper is not None:
                try:
                    scraper.close()
                except Exception:
                    pass

    return best_nodes


def parse_subscription_content(content: str) -> list[ProxyNode]:
    """解析订阅内容，返回节点列表"""
    decoded = detect_and_decode(content)
    nodes = []

    # 尝试 YAML 格式（Clash 配置）
    if decoded.strip().startswith("proxies:") or "mixed-port" in decoded:
        try:
            yaml_data = yaml.safe_load(decoded)
            if isinstance(yaml_data, dict) and "proxies" in yaml_data:
                for p in yaml_data["proxies"]:
                    try:
                        nodes.append(_yaml_to_node(p))
                    except Exception as e:
                        # 单条坏条目跳过，不拖垮整份 YAML
                        logger.warning("YAML 单条 proxy 解析失败，已跳过: %s", e)
                if nodes:
                    return nodes
        except Exception as e:
            logger.warning("YAML 订阅解析失败，回退逐行解析: %s", e)

    # 逐行解析 URI
    for line in decoded.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过注释和非 URI 行
        if line.startswith("#") or line.startswith("//"):
            continue
        node = parse_node_uri(line)
        if node:
            nodes.append(node)

    # 过滤无效节点
    nodes = [n for n in nodes if _is_valid_node(n)]

    return _dedupe_nodes(nodes)


def _dedupe_nodes(nodes: list[ProxyNode]) -> list[ProxyNode]:
    """同名节点加后缀去重"""
    seen = {}
    for n in nodes:
        if n.name in seen:
            idx = 2
            while f"{n.name}_{idx}" in seen:
                idx += 1
            n.name = f"{n.name}_{idx}"
        seen[n.name] = n
    return list(seen.values())


def parse_subscription_urls(urls: list) -> list[ProxyNode]:
    """解析多个订阅 URL 并合并节点（跨订阅同名去重）"""
    all_nodes = []
    for url in urls:
        try:
            ns = parse_subscription_url(url)
            logger.info("订阅 %s 解析到 %d 个节点", _mask_url(url), len(ns))
            all_nodes.extend(ns)
        except Exception as e:
            logger.warning("订阅 %s 解析失败: %s", _mask_url(url), e)
    return _dedupe_nodes(all_nodes)


# mihomo 支持的代理类型（2026-08 用 mihomo v1.19 实测 -t 校验；
# 白名单外节点不进 mihomo 配置，避免单条不支持类型导致整份配置加载失败）
MIHOMO_SUPPORTED_TYPES = {"ss", "ssr", "vmess", "vless", "trojan", "hysteria",
                          "hysteria2", "tuic", "anytls", "wireguard",
                          "socks5", "http", "ssh"}


def _is_valid_node(n: ProxyNode) -> bool:
    """过滤掉非真实节点的条目"""
    # 排除本地地址
    if n.server in ("127.0.0.1", "0.0.0.0", "localhost", "", "::1"):
        return False
    # 排除端口 0
    if n.port == 0:
        return False
    # 排除名字含关键词的信息行
    skip_keywords = ["剩余流量", "套餐到期", "重置", "客户端不支持", "请用官网"]
    for kw in skip_keywords:
        if kw in n.name:
            return False
    # mihomo 不支持的类型（shadowtls/naive/juicity 等）不进测速流程
    if n.type not in MIHOMO_SUPPORTED_TYPES:
        logger.warning("节点 %s 类型 %s 不被 mihomo 支持，已过滤", n.name, n.type)
        return False
    # wireguard 必须有 public-key 才能连通
    if n.type == "wireguard" and not n.extra.get("public-key"):
        logger.warning("节点 %s wireguard 缺少 public-key，已过滤", n.name)
        return False
    return True


def _yaml_to_node(p: dict) -> ProxyNode:
    """将 Clash YAML proxy 条目转换为 ProxyNode"""
    if not isinstance(p, dict):
        raise ValueError(f"proxy 条目不是字典: {type(p).__name__}")
    extra = {}
    for k, v in p.items():
        if k in ("name", "type", "server", "port"):
            continue
        extra[k] = v
    return ProxyNode(
        name=str(p.get("name", "")),
        type=str(p.get("type", "")),
        server=str(p.get("server", "")),
        port=int(p.get("port") or 0),
        extra=extra,
    )


def parse_node_uri(line: str) -> Optional[ProxyNode]:
    """解析单行 URI"""
    line = line.strip()
    for prefix, parser in PARSERS.items():
        if line.startswith(prefix):
            return parser(line)
    return None


# ═══════════════════════════════════════════════════════════════
#  TCP Ping 延迟测试
# ═══════════════════════════════════════════════════════════════

async def tcp_ping(host: str, port: int, timeout: float = 3.0) -> Optional[float]:
    """TCP 连接延迟测试，返回毫秒"""
    try:
        t0 = time.monotonic()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        elapsed = (time.monotonic() - t0) * 1000
        writer.close()
        await writer.wait_closed()
        return elapsed
    except (asyncio.TimeoutError, OSError):
        return None
    except Exception:
        return None


async def tcp_ping_retry(host: str, port: int, attempts: int = 2,
                         timeouts: tuple = (2.0, 3.0)) -> Optional[float]:
    """TCP Ping 带重试（瞬态失败容错），返回各次成功值中的最小值"""
    best = None
    for i in range(attempts):
        t = await tcp_ping(host, port, timeouts[min(i, len(timeouts) - 1)])
        if t is not None:
            best = t if best is None else min(best, t)
        if i < attempts - 1:
            await asyncio.sleep(0.3)  # 重试间隔，给瞬态拥塞恢复时间
    return best


async def run_tcp_ping(nodes: list[ProxyNode], concurrency: int = TCP_PING_CONCURRENCY) -> dict:
    """并发 TCP Ping 所有节点（UDP/QUIC 系协议节点跳过，由 mihomo 实测可达性）"""
    sem = asyncio.Semaphore(concurrency)

    async def ping_one(node: ProxyNode) -> tuple[ProxyNode, Optional[float]]:
        async with sem:
            if is_udp_node(node):
                return node, None
            latency = await tcp_ping_retry(node.server, node.port)
            return node, latency

    tasks = [ping_one(n) for n in nodes]
    results = {}
    pbar = tqdm(total=len(nodes), desc="TCP Ping", unit="节点", mininterval=1.0)
    for coro in asyncio.as_completed(tasks):
        node, latency = await coro
        results[node.name] = latency
        if is_udp_node(node):
            label = "UDP跳过"
        elif latency:
            label = f"{latency:.0f}ms"
        else:
            label = "超时"
        pbar.set_postfix_str(f"{_flag_to_text(node.name)} {label}", refresh=False)
        pbar.update(1)
        logger.debug(
            "TCP %s %s", node.name, label,
            extra=_ev("tcp_ping", {"node": node.name, "type": node.type, "result": label}))
    pbar.close()
    return results


async def run_tcp_probe_pool(binary_path: str, candidates: list[ProxyNode]) -> dict:
    """TCP 来源B：经 mihomo 隧道并发探测节点可达性（直连失败节点兜底 + UDP 节点）

    每个候选占一个独立 worker（并发 TCP_PROBE_CONCURRENCY 路），
    经节点隧道请求 gstatic 204 判定可达。返回 {节点名: bool}
    """
    if not candidates or not binary_path or not os.path.isfile(binary_path):
        return {}
    size = min(TCP_PROBE_CONCURRENCY, len(candidates))
    pool = MihomoWorkerPool(binary_path, size)
    if not await pool.start():
        return {}
    results: dict = {}
    queue: asyncio.Queue = asyncio.Queue()
    for n in candidates:
        await queue.put(n)
    for _ in pool.workers:
        await queue.put(None)  # 终止哨兵

    ssl_ctx = _no_verify_ssl()
    pbar = tqdm(total=len(candidates), desc="TCP探测", unit="节点", mininterval=1.0)

    async def probe_loop(worker: MihomoWorker):
        while True:
            node = await queue.get()
            if node is None:
                queue.task_done()
                return
            ok = False
            try:
                pbar.set_postfix_str(f"{_flag_to_text(node.name)} 探测中")
                if await worker.load_node(node):
                    try:
                        async with aiohttp.ClientSession(
                                connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
                            async with sess.get(
                                    "https://www.gstatic.com/generate_204",
                                    proxy=worker.get_proxy_url(),
                                    timeout=aiohttp.ClientTimeout(total=TCP_PROBE_TIMEOUT),
                            ) as resp:
                                ok = resp.status == 204
                    except Exception:
                        ok = False
            except Exception:
                ok = False
            results[node.name] = ok
            logger.debug(
                "隧道探测 %s %s", node.name, "可达" if ok else "不可达",
                extra=_ev("tcp_probe", {"node": node.name, "reachable": ok}))
            pbar.set_postfix_str(
                f"{_flag_to_text(node.name)} {'可达' if ok else '不可达'}", refresh=False)
            queue.task_done()
            pbar.update(1)

    try:
        await asyncio.gather(*[probe_loop(w) for w in pool.workers])
    finally:
        pbar.close()
        await pool.stop()  # 中断/异常时也必须回收探测池，防止泄漏 mihomo 进程
    return results


# ═══════════════════════════════════════════════════════════════
#  Mihomo 引擎管理
# ═══════════════════════════════════════════════════════════════

class MihomoEngine:
    """mihomo (clash-meta) 引擎管理"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.mixed_port = self._find_free_port(7890)
        self.api_port = self._find_free_port(9090)
        self.binary_path = self._find_or_download()
        self.config_path = ""
        self._ready = False

    @staticmethod
    def _find_free_port(start: int) -> int:
        """找可用端口，范围放宽"""
        import socket
        for port in range(start, 60000):
            try:
                with socket.socket() as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue
        return start

    @staticmethod
    def _find_or_download() -> str:
        """查找或下载 mihomo 二进制"""
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        # 查找已有二进制
        for f in os.listdir(MIHOMO_DIR):
            if f.startswith("mihomo") and (f.endswith(".exe") or "." not in f):
                return os.path.join(MIHOMO_DIR, f)
        # 需要下载
        print("未找到 mihomo 内核，正在下载...")
        binary = MihomoEngine._download_mihomo()
        if binary:
            return binary
        logger.warning("mihomo 下载失败，部分功能不可用")
        return ""

    @staticmethod
    def _get_latest_tag() -> str:
        """获取最新 mihomo 版本号，避免 GitHub API 限速"""
        # 方法1: 通过 releases/latest 重定向获取 tag
        try:
            r = _requests.get(
                f"https://github.com/{MIHOMO_REPO}/releases/latest",
                allow_redirects=True, timeout=10
            )
            if r.status_code == 200:
                tag = r.url.rstrip("/").split("/")[-1]
                if tag.startswith("v"):
                    return tag
        except Exception:
            pass
        # 方法2: 尝试 GitHub API (可能被限速)
        try:
            r = _requests.get(
                f"https://api.github.com/repos/{MIHOMO_REPO}/releases/latest",
                timeout=10, headers={"User-Agent": "speed_test.py/1.0"}
            )
            if r.status_code == 200:
                return r.json()["tag_name"]
        except Exception:
            pass
        return ""

    @staticmethod
    def _download_mihomo(target_dir: str = None) -> str:
        """下载最新 mihomo 到 target_dir（默认 MIHOMO_DIR），成功返回二进制路径"""
        target_dir = target_dir or MIHOMO_DIR
        os.makedirs(target_dir, exist_ok=True)
        try:
            tag = MihomoEngine._get_latest_tag()
            if not tag:
                return ""

            # 确定平台
            system = sys.platform
            if system == "win32":
                plat = "windows-amd64"
                ext = ".exe"
            elif system == "linux":
                plat = "linux-amd64"
                ext = ""
            elif system == "darwin":
                plat = "darwin-amd64"
                ext = ""
            else:
                return ""

            # 可能的文件名模式
            candidates = [
                f"mihomo-{plat}-{tag}.zip",
                f"mihomo-{plat}.zip",
                f"mihomo-{plat}-alpha-{tag}.zip",
            ]

            base_url = f"https://github.com/{MIHOMO_REPO}/releases/download/{tag}"
            zip_path = None

            for fname in candidates:
                url = f"{base_url}/{fname}"
                try:
                    print(f"  尝试: {fname}")
                    zip_resp = _requests.get(url, stream=True, timeout=30)
                    if zip_resp.status_code == 200:
                        total = int(zip_resp.headers.get("content-length", 0))
                        zip_path = os.path.join(target_dir, fname)
                        with open(zip_path, "wb") as f:
                            downloaded = 0
                            for chunk in zip_resp.iter_content(8192):
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total:
                                    pct = downloaded / total * 100
                                    print(f"\r  下载中: {pct:.0f}%", end="", flush=True)
                        logger.info(f"下载完成: {fname} ({total/1024/1024:.1f}MB)")
                        break
                except Exception as e:
                    logger.warning(f"下载 {fname} 失败: {e}")
                    continue

            if not zip_path or not os.path.exists(zip_path):
                return ""

            # 解压（校验 zip-slip：条目路径不得越出 target_dir）
            base_real = os.path.realpath(target_dir)
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        tgt = os.path.realpath(os.path.join(target_dir, name))
                        if not (tgt == base_real or tgt.startswith(base_real + os.sep)):
                            raise RuntimeError(f"非法压缩包路径: {name}")
                    zf.extractall(target_dir)
            except Exception as e:
                logger.error(f"解压失败: {e}")
                os.remove(zip_path)
                return ""
            os.remove(zip_path)

            # 找到解压后的二进制
            for root, _, files in os.walk(target_dir):
                for f in files:
                    if "mihomo" in f.lower() and (f.endswith(".exe") or "." not in f):
                        binary_path = os.path.join(root, f)
                        dst = os.path.join(target_dir, f"mihomo{ext}")
                        if binary_path != dst:
                            shutil.move(binary_path, dst)
                        if ext != ".exe":
                            os.chmod(dst, 0o755)
                        logger.info(f"mihomo 已就绪: {dst}")
                        return dst
            return ""
        except Exception as e:
            logger.error(f"mihomo 下载失败: {e}")
            return ""

    def generate_config(self, nodes: list[ProxyNode]) -> str:
        """生成 Clash 配置文件"""
        config = _build_config_dict(nodes, self.mixed_port, self.api_port)
        # 写入临时文件
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="mihomo_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        self.config_path = path
        return path

    async def start(self):
        """启动 mihomo 进程"""
        if not self.binary_path:
            raise RuntimeError("mihomo 二进制不存在")
        if self.process and self._ready:
            return
        self.process = subprocess.Popen(
            [self.binary_path, "-f", self.config_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 等待 API 就绪
        async with aiohttp.ClientSession() as sess:
            for i in range(30):
                await asyncio.sleep(0.5)
                try:
                    async with sess.get(f"http://127.0.0.1:{self.api_port}/version", timeout=2) as resp:
                        if resp.status == 200:
                            self._ready = True
                            return
                except Exception:
                    continue
        self._ready = False
        raise RuntimeError("mihomo 启动超时")

    async def stop(self):
        """停止 mihomo"""
        if self.process:
            self.process.terminate()
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self.process.wait),
                    timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await loop.run_in_executor(None, self.process.wait)
            self.process = None
            self._ready = False
        # 清理配置
        if self.config_path and os.path.exists(self.config_path):
            try:
                os.remove(self.config_path)
            except Exception:
                pass

    async def switch_proxy(self, name: str) -> bool:
        """切换到指定节点并校验生效（防止测速走错出口）"""
        if not self._ready:
            return False
        async with aiohttp.ClientSession() as sess:
            for attempt in range(2):
                try:
                    async with sess.put(
                        f"http://127.0.0.1:{self.api_port}/proxies/Auto",
                        json={"name": name},
                        timeout=5,
                    ) as resp:
                        if resp.status != 204:
                            break
                except Exception:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    return False
                # 校验生效：轮询 Auto 组当前选中节点
                if await _wait_auto_selected(self.api_port, name):
                    return True
                if attempt == 0:
                    continue
        return False

    def get_proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.mixed_port}"

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()


def _build_config_dict(nodes: list[ProxyNode], mixed_port: int, api_port: int) -> dict:
    """构建 Clash 配置字典（单实例全节点 / 并行 worker 单节点共用）"""
    return {
        "mixed-port": mixed_port,
        "external-controller": f"127.0.0.1:{api_port}",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "silent",
        "ipv6": True,  # 允许 IPv6 节点（v4 节点不受影响）
        "proxies": [n.to_clash_proxy() for n in nodes],
        "proxy-groups": [
            {
                "name": "Auto",
                "type": "select",
                "proxies": [n.name for n in nodes] + ["DIRECT"],
            }
        ],
        "rules": [
            "MATCH,Auto",
        ],
    }


async def _wait_auto_selected(api_port: int, name: str, timeout: float = 3.0,
                              interval: float = 0.2, request_timeout: float = 1.0) -> bool:
    """轮询 mihomo API，直到 Auto 组当前选中节点 == name（引擎与 worker 共用）"""
    async with aiohttp.ClientSession() as sess:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with sess.get(
                        f"http://127.0.0.1:{api_port}/proxies/Auto",
                        timeout=request_timeout) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data.get("now") == name:
                            return True
            except Exception:
                pass
            await asyncio.sleep(interval)
    return False


# ═══════════════════════════════════════════════════════════════
#  并行 mihomo 工作池（每 worker 恒绑定一个节点，热重载切换）
# ═══════════════════════════════════════════════════════════════

class MihomoWorker:
    """单个 mihomo 工作进程：一次只服务一个节点，通过 PUT /configs 热重载切换"""

    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.process: Optional[subprocess.Popen] = None
        self.mixed_port = MihomoEngine._find_free_port(17890)
        self.api_port = MihomoEngine._find_free_port(19090)
        self.config_path = ""
        self._ready = False

    def _write_config(self, nodes: list[ProxyNode]) -> str:
        config = _build_config_dict(nodes, self.mixed_port, self.api_port)
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="mihomo_worker_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        self.config_path = path
        return path

    async def _wait_ready(self, timeout: float = 15.0) -> bool:
        async with aiohttp.ClientSession() as sess:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    async with sess.get(f"http://127.0.0.1:{self.api_port}/version", timeout=2) as resp:
                        if resp.status == 200:
                            self._ready = True
                            return True
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        self._ready = False
        return False

    async def start(self) -> bool:
        """以空配置启动 worker"""
        self._write_config([])
        self.process = subprocess.Popen(
            [self.binary_path, "-f", self.config_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return await self._wait_ready()

    async def stop(self):
        """停止 worker 并清理配置"""
        if self.process:
            self.process.terminate()
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self.process.wait), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await loop.run_in_executor(None, self.process.wait)
            self.process = None
            self._ready = False
        if self.config_path and os.path.exists(self.config_path):
            try:
                os.remove(self.config_path)
            except Exception:
                pass

    async def _reload_config(self, nodes: list[ProxyNode]) -> bool:
        """PUT /configs 热重载（JSON body: path + payload）"""
        payload = yaml.dump(
            _build_config_dict(nodes, self.mixed_port, self.api_port),
            allow_unicode=True, default_flow_style=False)
        async with aiohttp.ClientSession() as sess:
            async with sess.put(
                f"http://127.0.0.1:{self.api_port}/configs?force=true",
                json={"path": "", "payload": payload},
                timeout=10,
            ) as resp:
                return resp.status == 204

    async def _verify_node(self, name: str, timeout: float = 3.0) -> bool:
        """校验 Auto 组当前选中节点是否为目标节点（共享轮询实现）"""
        return await _wait_auto_selected(self.api_port, name, timeout=timeout)

    async def load_node(self, node: ProxyNode) -> bool:
        """热加载单节点配置并校验生效；失败则重启该 worker 兜底"""
        if not self._ready:
            return False
        for attempt in range(2):
            try:
                if await self._reload_config([node]) and await self._verify_node(node.name):
                    return True
            except Exception:
                pass
            if attempt == 0:
                # 热重载失败 → 重启 worker（带目标节点配置重新拉起）
                logger.warning("worker 热重载失败，重启中 (node=%s)", node.name)
                await self.stop()
                self._write_config([node])
                self.process = subprocess.Popen(
                    [self.binary_path, "-f", self.config_path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if not await self._wait_ready():
                    return False
        return False

    def get_proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.mixed_port}"


class MihomoWorkerPool:
    """mihomo 并行工作进程池：N 个 worker 同时服务 N 个节点"""

    def __init__(self, binary_path: str, workers: int = DEFAULT_WORKERS):
        self.binary_path = binary_path
        self.size = max(1, min(int(workers), MAX_WORKERS))
        self.workers: list[MihomoWorker] = []

    async def start(self) -> bool:
        """启动全部 worker，任一失败则整体回收并返回 False（调用方回退串行）"""
        try:
            for _ in range(self.size):
                w = MihomoWorker(self.binary_path)
                self.workers.append(w)  # 先登记，启动失败也能被 stop() 回收
                if not await w.start():
                    raise RuntimeError("worker 启动超时")
        except Exception as e:
            logger.error(f"并行池启动失败: {e}")
            await self.stop()
            return False
        return bool(self.workers)

    async def stop(self):
        for w in self.workers:
            try:
                await w.stop()
            except Exception:
                pass
        self.workers.clear()


# ═══════════════════════════════════════════════════════════════
#  HTTP 速度测试
# ═══════════════════════════════════════════════════════════════

async def test_node_speed(mihomo, node: ProxyNode) -> tuple:
    """通过 mihomo 测试节点 HTTP 延迟和下载速度（单节点多连接多源聚合）

    返回 (http_latency, speed, max_speed, per_sec, error_note)

    可靠性设计：
    - DOWNLOAD_CONNS 路并发连接，轮流取 SPEED_TEST_URLS（至少 2 个源）
    - 窗口从首个字节起计时，窗口满即取消其余连接（不等慢连接）
    - 平均速度排除首秒槽（TCP 慢启动剥离），峰值取每秒最大槽
    - 前 SLOW_ABORT_SECONDS 秒累计下载 < SLOW_ABORT_BYTES → 提前终止
    """
    proxy = mihomo.get_proxy_url()
    http_latency = None
    speed = None
    max_speed = None
    per_sec = []   # 确保任何异常路径下都有定义
    error_note = None
    window_secs = SPEED_WINDOW_SECONDS
    num_slots = int(window_secs)
    try:
        ssl_ctx = _no_verify_ssl()
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        async with aiohttp.ClientSession(connector=connector) as sess:
            # 先测 HTTP 延迟（失败不阻塞测速）
            try:
                t0 = time.monotonic()
                async with sess.get(
                    "https://www.gstatic.com/generate_204",
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=HTTP_LATENCY_TIMEOUT),
                ) as resp:
                    if resp.status == 204:
                        http_latency = (time.monotonic() - t0) * 1000
            except Exception:
                pass

            # 多连接多源下载（4 连接轮流取源；油管直链解析成功时作为第 4 个源）
            urls = list(SPEED_TEST_URLS)
            if _YOUTUBE_DL_URL:
                urls.append(_YOUTUBE_DL_URL)
            slot_bytes = [0] * num_slots
            downloaded = 0
            t_first = None
            aborted_slow = False
            finished = asyncio.Event()

            async def download_one(i: int):
                """单路下载任务：连接 i 取第 i % len(urls) 个源"""
                nonlocal downloaded, t_first, aborted_slow
                url = urls[i % len(urls)]
                got = 0
                status = None
                try:
                    async with sess.get(
                        url,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=HTTP_DOWNLOAD_TIMEOUT),
                    ) as resp:
                        status = resp.status
                        if resp.status != 200:
                            return
                        async for chunk in resp.content.iter_chunked(65536):
                            if finished.is_set():
                                return
                            if t_first is None:
                                t_first = time.monotonic()
                            elapsed = time.monotonic() - t_first
                            if elapsed >= window_secs:
                                finished.set()  # 窗口已满
                                return
                            idx = max(0, min(int(elapsed), num_slots - 1))
                            slot_bytes[idx] += len(chunk)
                            downloaded += len(chunk)
                            got += len(chunk)
                            # 慢节点提前终止
                            if elapsed >= SLOW_ABORT_SECONDS and downloaded < SLOW_ABORT_BYTES:
                                aborted_slow = True
                                logger.debug(
                                    "慢节点提前终止: %s", node.name,
                                    extra=_ev("speed_abort_slow",
                                              {"node": node.name, "downloaded_bytes": downloaded}))
                                finished.set()
                                return
                except Exception as e:
                    logger.debug("test_node_speed conn %d failed for %s: %s", i, node.name, e,
                                 extra=_ev("speed_conn_error",
                                           {"node": node.name, "conn": i, "error": str(e)[:200]}))
                finally:
                    host = urlparse(url).netloc
                    logger.debug(
                        "测速 conn%d 源=%s 状态=%s 下载=%d 字节", i, host, status, got,
                        extra=_ev("speed_conn", {
                            "node": node.name, "conn": i, "source": host,
                            "status": status, "bytes": got}))

            tasks = [asyncio.ensure_future(download_one(i)) for i in range(DOWNLOAD_CONNS)]
            all_done = asyncio.gather(*tasks, return_exceptions=True)
            window_waiter = asyncio.ensure_future(finished.wait())
            try:
                await asyncio.wait_for(
                    asyncio.wait([all_done, window_waiter], return_when=asyncio.FIRST_COMPLETED),
                    timeout=HTTP_DOWNLOAD_TIMEOUT,
                )
            except asyncio.TimeoutError:
                pass
            if not all_done.done():
                # 窗口已满/超时但仍有连接在跑 → 取消并收割（带超时保险）
                for t in tasks:
                    t.cancel()
                try:
                    await asyncio.wait_for(all_done, timeout=5)
                except asyncio.TimeoutError:
                    pass
            if not window_waiter.done():
                window_waiter.cancel()

            # 结果统计
            window_time = min(time.monotonic() - t_first, window_secs) if t_first is not None else 0.0
            if aborted_slow:
                error_note = "速度过低"
            elif downloaded >= MIN_SPEED_BYTES and window_time > 0:
                # 每秒速度：完整秒槽按 1s 折算，末个不满 1 秒的槽按实际秒数折算
                per_sec = []
                full_slots = int(window_time)
                for i in range(num_slots):
                    b = slot_bytes[i]
                    if i < full_slots:
                        per_sec.append((b / 1.0) / (1024 * 1024))
                    elif i == full_slots:
                        frac = window_time - full_slots
                        if frac < 0.25:
                            frac = 0.25  # 下限：避免极短末槽瞬时突发把峰值放大数倍
                        per_sec.append((b / frac) / (1024 * 1024))
                    else:
                        per_sec.append(0.0)
                max_speed = max(per_sec) if per_sec else speed
                # 平均速度：排除首秒慢启动（窗口≥2s 时按 窗口-1s 折算）
                if window_time >= 2.0 and full_slots >= 2:
                    speed = ((downloaded - slot_bytes[0]) / (window_time - 1.0)) / (1024 * 1024)
                else:
                    speed = (downloaded / window_time) / (1024 * 1024)
            else:
                error_note = "下载失败"  # 数据量不足（连接失败/拦截页）
    except Exception as e:
        logger.debug("test_node_speed stats failed for %s: %s", node.name, e)
    return http_latency, speed, max_speed, per_sec, error_note


async def _pbar_ticker(pbar, stop_event: asyncio.Event) -> None:
    """每秒刷新一次进度条显示（cmd 控制台每秒更新）"""
    try:
        while not stop_event.is_set():
            pbar.refresh()
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass


async def run_speed_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                         results: dict[str, TestResult]) -> None:
    """运行 HTTP 速度测试（串行：单节点单时刻，节点内部多连接）"""
    pbar = tqdm(total=len(nodes), desc="HTTP测速", unit="节点", mininterval=1.0)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    try:
        for i, node in enumerate(nodes):
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 测速中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                logger.warning("切换节点失败: %s", node.name,
                               extra=_ev("switch_node", {"node": node.name, "ok": False}))
                pbar.set_postfix_str(f"{display} 切换失败", refresh=False)
                pbar.update(1)
                continue
            logger.debug("切换节点: %s", node.name,
                         extra=_ev("switch_node", {"node": node.name, "ok": True}))
            await asyncio.sleep(0.2)
            http_latency, speed, max_speed, per_sec, err_note = await test_node_speed(mihomo, node)
            if node.name in results:
                results[node.name].http_latency = http_latency
                results[node.name].speed = speed
                results[node.name].max_speed = max_speed
                results[node.name].speed_per_sec = per_sec
                if err_note:
                    results[node.name].error = err_note
            logger.info(
                "测速 %s 延迟=%s 平均=%s 峰值=%s %s",
                node.name,
                f"{http_latency:.0f}ms" if http_latency else "--",
                f"{speed:.1f}MB/s" if speed else "--",
                f"{max_speed:.1f}MB/s" if max_speed else "--",
                err_note or "",
                extra=_ev("speed_done", {
                    "node": node.name,
                    "http_latency_ms": http_latency,
                    "avg_mbs": speed,
                    "max_mbs": max_speed,
                    "error": err_note or None,
                }),
            )
            pbar.set_postfix_str(
                f"{display} "
                f"{f'{http_latency:.0f}ms' if http_latency else '--'} "
                f"{f'{speed:.1f}MB/s' if speed else (err_note or '--')}",
                refresh=False,
            )
            pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()


# ═══════════════════════════════════════════════════════════════
#  流媒体解锁检测
# ═══════════════════════════════════════════════════════════════

async def check_youtube(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 YouTube Premium 解锁，如果 Premium 送中则回退到普通 YouTube"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,en;q=0.9",
        }
        async with session.get(
            "https://www.youtube.com/premium", proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
        ) as resp:
            text = await resp.text()
            # 送中检测
            if "www.google.cn" in text:
                # 回退检测普通 YouTube 是否可访问
                try:
                    async with session.get("https://www.youtube.com", proxy=proxy,
                        headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r2:
                        if r2.status == 200:
                            return "可用(CN)"
                except Exception:
                    pass
                return "送中(CN)"
            # 区域不可用
            if "Premium is not available in your country" in text:
                return "失败(区域限制)"
            # 提取地区
            region = ""
            m = re.search(r'"countryCode":"([A-Z]{2})"', text)
            if m:
                region = m.group(1)
            if not region:
                m = re.search(r'"INNERTUBE_CONTEXT_GL"\s*:\s*"([A-Z]{2})"', text)
                if m:
                    region = m.group(1)
            # ad-free 标识=解锁
            if "ad-free" in text or "YouTube and YouTube Music ad-free" in text:
                if region:
                    return f"解锁({region})"
                return "解锁(未知)"
            # 有地区代码但无 ad-free → 无 Premium 解锁但 YouTube 可访问
            if region:
                return f"可用({region})"
            return "失败(无Premium标识)"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_netflix(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Netflix 解锁（参考 RegionRestrictionCheck）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async def _check(url: str) -> str:
            try:
                async with session.get(url, proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                ) as r:
                    if r.status != 200:
                        return "blocked"
                    t = await r.text()
                    if "Not Available" in t or "not available" in t:
                        return "blocked"
                    region = ""
                    m = re.search(r'"country"\s*:\s*"([A-Z]{2})"', t)
                    if m:
                        region = m.group(1)
                    return f"ok:{region}" if region else "ok"
            except Exception:
                return "错误(连接失败)"  # 连接类异常与业务封锁区分，供死节点预检判定

        r1 = await _check("https://www.netflix.com/title/81280792")  # 自制剧
        r2 = await _check("https://www.netflix.com/title/70143836")  # 非自制剧

        if r1.startswith("错误") or r2.startswith("错误"):
            return "错误(连接失败)"
        if r1.startswith("ok") and r2.startswith("ok"):
            region = r1.split(":")[1] if ":" in r1 else r2.split(":")[1] if ":" in r2 else ""
            return f"解锁({region})" if region else "解锁"
        elif r1.startswith("ok") and not r2.startswith("ok"):
            return "仅自制剧"
        else:
            return "失败"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_disney(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Disney+（跟进重定向）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with session.get(
            "https://www.disneyplus.com/", proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
        ) as resp:
            if resp.status == 200:
                return "解锁"
            elif resp.status == 403:
                return "封锁"
            return f"({resp.status})"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_chatgpt(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 ChatGPT（多端点探测）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        async def _probe(url: str) -> tuple[int, str]:
            """探测一个端点，返回 (status, text)"""
            try:
                async with session.get(url, proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=8),
                    allow_redirects=True) as r:
                    t = await r.text()
                    return r.status, t
            except Exception:
                return 0, ""

        # 优先探测 chatgpt.com 主站
        status1, _ = await _probe("https://chatgpt.com/")
        if status1 == 200:
            return "解锁"

        # 再试 chat.openai.com favicon
        status2, _ = await _probe("https://chat.openai.com/favicon.ico")
        if status2 == 200:
            return "解锁"

        # 试 cdn-cgi/trace 提取地区
        _, trace = await _probe("https://chat.openai.com/cdn-cgi/trace")
        region = ""
        for line in trace.splitlines():
            if line.startswith("loc="):
                region = line[4:].strip()
                break

        # favicon 403 + trace 有地区 → CF 拦截了路径但能通
        if status2 == 403 and region:
            return f"解锁({region})"
        # trace 有地区 → 能通
        if region:
            return f"解锁({region})"
        # 全部失败
        if status2 == 403:
            return "封锁"
        return "错误(连接失败)"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_generic(session: aiohttp.ClientSession, proxy: str, url: str, name: str) -> str:
    """通用检测（跟进重定向，允许 3xx 也算可用）"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with session.get(
            url, proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            status = resp.status
            # 有些服务返回 3xx/404 但也算可访问（如某些仅登录后可见的平台）
            if status in (200, 201, 202, 204, 301, 302, 303, 307, 308):
                return "可用"
            # 403 可能是 Cloudflare 拦截，但如果响应内容里有正常页面文字也算可用
            if status == 403:
                text = await resp.text()
                if any(kw in text for kw in ["<html", "<!DOCTYPE", "window.__NUXT",
                                               "react-root"]):
                    return "可用"
                return "封锁"
            return f"({status})"
    except aiohttp.ClientResponseError as e:
        status = e.status if hasattr(e, 'status') else 0
        if status in (200, 201, 202, 204, 301, 302, 303, 307, 308):
            return "可用"
        if status == 403:
            return "封锁"
        if status > 0:
            return f"({status})"
        return "错误(连接失败)"
    except Exception:
        return "错误(连接失败)"


async def check_bilibili(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Bilibili 可访问性"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with session.get(
            "https://www.bilibili.com",
            proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
        ) as resp:
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception as e:
        return f"错误({type(e).__name__})"


# B站港澳台检测剧集 ep_id（2026-08 实测校准：台湾节点可播、新加坡节点 -10403 区域限制）
BILI_TW_EP_IDS = [268176, 268177, 268178, 268173]


async def check_bilibili_tw(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 B站港澳台解锁：TW-only 番剧 playurl 是否返回可播放流"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        }
        for ep in BILI_TW_EP_IDS:
            try:
                async with session.get(
                    f"https://api.bilibili.com/pgc/player/web/playurl?ep_id={ep}"
                    "&qn=0&otype=json&fnval=16&fourk=1&module=bangumi",
                    proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                ) as resp:
                    data = await resp.json()
                code = data.get("code", -1)
                msg = str(data.get("message", ""))
                if "区域" in msg or "版权" in msg or "地区" in msg:
                    return "失败(区域限制)"
                if code == 0:
                    res = data.get("result") or {}
                    if res.get("durl") or res.get("dash"):
                        return "解锁(港澳台)"
            except Exception:
                continue
        return "失败"
    except Exception as e:
        return f"错误({type(e).__name__})"


_STREAM_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def check_tiktok(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 TikTok 解锁：从页面提取地区码，区分风控页"""
    try:
        async with session.get(
            "https://www.tiktok.com/explore", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            region = ""
            for pat in (r'"region":"([A-Z]{2})"', r'"region":\s*"([A-Z]{2})"',
                        r'"appRegion":"([A-Z]{2})"'):
                m = re.search(pat, text)
                if m:
                    region = m.group(1)
                    break
            if resp.status != 200:
                return f"({resp.status})"
            low = text.lower()
            if ("is-verify" in low or "captcha" in low or "access denied" in low) and not region:
                return "失败(风控)"
            if region:
                return f"解锁({region})"
            return "可用"
    except Exception:
        return "错误(连接失败)"


async def check_spotify(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Spotify 解锁：地区重定向 / 页面 territory 字段"""
    try:
        async with session.get(
            "https://www.spotify.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=False,
        ) as resp:
            if resp.status in (301, 302, 307, 308):
                loc = resp.headers.get("Location", "")
                m = re.search(r"spotify\.com/([a-z]{2})(/|$)", loc)
                if m:
                    return f"解锁({m.group(1).upper()})"
                return "可用"  # 有地区重定向但未携带国家码，视为可访问
            text = await resp.text()
            m = re.search(r'"territory":"([A-Z]{2})"', text)
            if not m:
                m = re.search(r"data-territory=\"([a-z]{2})\"", text)
            if m:
                return f"解锁({m.group(1).upper()})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_steam(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Steam 商店解锁：steamcountry 字段"""
    try:
        async with session.get(
            "https://store.steampowered.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            m = re.search(r'"steamcountry"\s*:\s*"([a-z]{2})"', text)
            if not m:
                m = re.search(r'"steamcountry":"([a-z]{2})"', text)
            if m:
                return f"解锁({m.group(1).upper()})"
            # cookie 兜底
            cc = resp.cookies.get("steamcountry")
            if cc:
                code = str(cc.value).split("%")[0][:2]
                if code.isalpha():
                    return f"解锁({code.upper()})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_primevideo(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Prime Video 解锁：territory 字段"""
    try:
        async with session.get(
            "https://www.primevideo.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            region = ""
            for pat in (r'"currentTerritory"\s*:\s*"([A-Z]{2})"',
                        r'"territory"\s*:\s*"([A-Z]{2})"',
                        r'"TerritoryCode"\s*:\s*"([A-Z]{2})"'):
                m = re.search(pat, text)
                if m:
                    region = m.group(1)
                    break
            if region:
                return f"解锁({region})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_max(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Max(HBO) 解锁：可用页 vs 区域不可用页"""
    try:
        async with session.get(
            "https://www.max.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            final_url = str(resp.url)
            if "not-available" in final_url or "unavailable" in final_url.lower():
                return "失败(区域不可用)"
            text = await resp.text()
            m = re.search(r'"countryCode"\s*:\s*"([A-Z]{2})"', text)
            if resp.status == 200:
                return f"解锁({m.group(1)})" if m else "解锁"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


STREAMING_CHECKERS = {
    "youtube": check_youtube,
    "netflix": check_netflix,
    "disney": check_disney,
    "chatgpt": check_chatgpt,
    "bilibili": check_bilibili,
    "bilibili_tw": check_bilibili_tw,
    "tiktok": check_tiktok,
    "spotify": check_spotify,
    "steam": check_steam,
    "primevideo": check_primevideo,
    "max": check_max,
}


async def check_one_node_streaming(session: aiohttp.ClientSession, proxy: str,
                                    node: ProxyNode, services: list = None) -> dict:
    """检测单个节点的流媒体（用指定服务列表，默认全部）

    可靠性设计：
    - 瞬时"错误"类结果重试一次（不重试明确的失败/封锁）
    - 死节点早期终止：先测前 3 个服务，全为连接失败 → 其余服务标"跳过"
    """
    if services is None:
        services = FULL_STREAMING_SERVICES

    async def _run_one(svc: dict) -> tuple[str, str]:
        sid = svc["id"]
        if sid in STREAMING_CHECKERS:
            result = await STREAMING_CHECKERS[sid](session, proxy)
        else:
            result = await check_generic(session, proxy, svc["url"], svc["name"])
        return sid, result

    async def _run_batch(batch: list) -> dict:
        """并发跑一批服务：异常/缺失条目统一记为错误(连接失败)"""
        results_list = await asyncio.gather(*[_run_one(s) for s in batch],
                                            return_exceptions=True)
        batch_dict = {}
        for item in results_list:
            if isinstance(item, tuple) and len(item) == 2:
                k, v = item
                batch_dict[k] = "错误(连接失败)" if isinstance(v, BaseException) else v
        for s in batch:  # 兜底：任何缺失 key 视为连接失败，保证可重试/可判定
            if s["id"] not in batch_dict:
                batch_dict[s["id"]] = "错误(连接失败)"
        return batch_dict

    async def _retry_errors(batch: list, batch_dict: dict) -> dict:
        """对"错误"类结果重试一次"""
        retry_svcs = [s for s in batch
                      if isinstance(batch_dict.get(s["id"]), str)
                      and batch_dict.get(s["id"], "").startswith("错误")]
        if retry_svcs:
            await asyncio.sleep(0.5)
            retry_list = await asyncio.gather(*[_run_one(s) for s in retry_svcs],
                                              return_exceptions=True)
            for item in retry_list:
                if isinstance(item, tuple) and len(item) == 2:
                    k, v = item
                    if not isinstance(v, BaseException):
                        batch_dict[k] = v
        return batch_dict

    if len(services) <= 3:
        return await _retry_errors(services, await _run_batch(services))

    # 死节点预检：前 3 个服务全为连接错误 → 其余服务不再实测
    first_batch = services[:3]
    result_dict = await _retry_errors(first_batch, await _run_batch(first_batch))
    if all(isinstance(v, str) and v.startswith("错误") for v in result_dict.values()):
        for s in services[3:]:
            result_dict[s["id"]] = "跳过(节点不可达)"
        return result_dict
    rest_dict = await _retry_errors(services[3:], await _run_batch(services[3:]))
    result_dict.update(rest_dict)
    return result_dict


def _log_streaming_details(node_name: str, streaming: dict) -> None:
    """JSONL 记录单节点流媒体汇总 + 每平台明细"""
    unlocked = sum(1 for v in streaming.values()
                   if "解锁" in v or "可用" in v or "成功" in v)
    logger.debug(
        "解锁 %s: %d/%d 平台", node_name, unlocked, len(streaming),
        extra=_ev("streaming_done", {"node": node_name, "unlocked": unlocked,
                                     "total": len(streaming)}))
    for sid, val in streaming.items():
        logger.debug(
            "流媒体 %s %s=%s", node_name, sid, val,
            extra=_ev("streaming_result", {"node": node_name, "service": sid, "result": val}))


def _log_ip_details(node_name: str, ip_info: dict) -> None:
    """JSONL 记录单节点 IP 检测结果"""
    logger.debug(
        "IP %s: %s 风险=%s", node_name, ip_info.get("ip", "?"),
        ip_info.get("risk_score", "?"),
        extra=_ev("ip_done", {
            "node": node_name, "ip": ip_info.get("ip"),
            "risk_score": ip_info.get("risk_score"),
            "share_level": ip_info.get("share_level"),
            "asn": ip_info.get("asn"),
            "org": ip_info.get("org"),
            "source": ip_info.get("source"),
        }))


async def run_streaming_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                              results: dict[str, TestResult],
                              services: list = None) -> None:
    """运行流媒体解锁检测（用指定服务列表）"""
    pbar = tqdm(total=len(nodes), desc="解锁检测", unit="节点", mininterval=1.0)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    ssl_ctx = _no_verify_ssl()
    try:
        for node in nodes:
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 检测中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                pbar.set_postfix_str(f"{display} 切换失败", refresh=False)
                pbar.update(1)
                continue
            await asyncio.sleep(0.3)
            proxy = mihomo.get_proxy_url()
            # 每个节点独立 session，防止连接复用导致走错出口
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
                streaming = await check_one_node_streaming(sess, proxy, node, services)
                if node.name in results:
                    results[node.name].streaming = streaming
                # 统计解锁数
                unlocked = sum(1 for v in streaming.values()
                              if "解锁" in v or "可用" in v or "成功" in v)
                _log_streaming_details(node.name, streaming)
                pbar.set_postfix_str(f"{display} {unlocked}/{len(streaming)}", refresh=False)
                pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()


# ═══════════════════════════════════════════════════════════════
#  IP 风控检测（类 ping0.cc）
# ═══════════════════════════════════════════════════════════════

def _heuristic_risk_score(info: dict) -> int:
    """启发式风控评分 0-100"""
    risk = 0
    if info.get("is_datacenter"):
        risk += 20
    if info.get("is_proxy"):
        risk += 25
    if info.get("is_vpn"):
        risk += 20
    if info.get("is_tor"):
        risk += 35
    if info.get("is_abuser"):
        risk += 25
    if info.get("is_crawler"):
        risk += 10
    return min(risk, 100)


def _heuristic_share_level(info: dict) -> str:
    """估算共享人数级别"""
    if info.get("is_datacenter"):
        if info.get("datacenter") is not None:
            return "1000-10000+"
        return "100-1000"
    if info.get("is_proxy") or info.get("is_vpn"):
        return "100-1000"
    if info.get("is_mobile"):
        return "10-100"
    return "1-10"


def _ipapi_to_info(data: dict) -> dict:
    """ipapi.is 响应 → 统一 IP 信息结构"""
    location = data.get("location", {})
    asn_info = data.get("asn", {})
    company = data.get("company", {})
    info = {
        "ip": data.get("ip", ""),
        "country": location.get("country", ""),
        "city": location.get("city", ""),
        "isp": location.get("isp", ""),
        "asn": f"AS{asn_info.get('asn', '')}" if asn_info.get("asn") else "",
        "org": asn_info.get("org", company.get("name", "")),
        "is_datacenter": data.get("is_datacenter", False),
        "is_proxy": data.get("is_proxy", False),
        "is_vpn": data.get("is_vpn", False),
        "is_tor": data.get("is_tor", False),
        "is_abuser": data.get("is_abuser", False),
        "is_mobile": data.get("is_mobile", False),
        "is_crawler": data.get("is_crawler", False),
        "datacenter": data.get("datacenter"),
        "source": "ipapi.is",
    }
    info["risk_score"] = _heuristic_risk_score(info)
    info["share_level"] = _heuristic_share_level(info)
    asn_country = asn_info.get("country", "")
    geo_country = location.get("country", "")
    info["is_native"] = (asn_country == geo_country) if (asn_country and geo_country) else None
    return info


def _ipwho_to_info(data: dict) -> dict:
    """ipwho.is 响应 → 统一 IP 信息结构"""
    location = data.get("connection", {})
    sec = data.get("security", {}) or {}
    ip_type = (data.get("type") or "").lower()
    info = {
        "ip": data.get("ip", ""),
        "country": data.get("country_code", ""),
        "city": data.get("city", ""),
        "isp": location.get("isp", ""),
        "asn": f"AS{location.get('asn', '')}" if location.get("asn") else "",
        "org": location.get("org", ""),
        "is_datacenter": bool(sec.get("hosting")) or ip_type in ("hosting", "business"),
        "is_proxy": bool(sec.get("proxy") or sec.get("anonymous")) or ip_type == "proxy",
        "is_vpn": bool(sec.get("vpn")),
        "is_tor": bool(sec.get("tor")),
        "is_abuser": None,
        "is_mobile": ip_type == "mobile",
        "is_crawler": None,
        "source": "ipwho.is",
    }
    info["risk_score"] = _heuristic_risk_score(info)
    info["share_level"] = _heuristic_share_level(info)
    info["is_native"] = None
    return info


def _ipsb_to_info(data: dict) -> dict:
    """api.ip.sb 响应 → 统一 IP 信息结构（无风控字段，不编造风险值）"""
    info = {
        "ip": data.get("ip", ""),
        "country": data.get("country_code", ""),
        "city": data.get("city", ""),
        "isp": data.get("isp", ""),
        "asn": f"AS{data.get('asn', '')}" if data.get("asn") else "",
        "org": data.get("organization", ""),
        "is_datacenter": None, "is_proxy": None, "is_vpn": None, "is_tor": None,
        "is_abuser": None, "is_mobile": None, "is_crawler": None,
        "source": "api.ip.sb",
    }
    info["risk_score"] = None  # 该源无风控数据
    info["share_level"] = "--"
    info["is_native"] = None
    return info


# IP 信息源回退链（主源 ipapi.is 数据最全；某源被节点出口封锁时自动换下一个）
IP_SOURCES = [
    ("https://api.ipapi.is", _ipapi_to_info),
    ("https://ipwho.is/", _ipwho_to_info),
    ("https://api.ip.sb/geoip", _ipsb_to_info),
]


async def check_ip_quality(session: aiohttp.ClientSession, proxy: str) -> dict:
    """通过代理检测出口 IP 质量（多源回退：ipapi.is → ipwho.is → api.ip.sb）"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    last_err = ""
    for url, mapper in IP_SOURCES:
        try:
            async with session.get(
                url,
                proxy=proxy,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=IP_QUALITY_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    last_err = f"HTTP {resp.status}"
                    logger.debug("IP 源 %s 返回 %s，换下一个源", url, last_err,
                                 extra=_ev("ip_source_attempt",
                                           {"source": url, "ok": False, "error": last_err}))
                    continue
                data = await resp.json()
            info = mapper(data)
            if not info.get("ip"):
                last_err = "响应无 IP 字段"
                logger.debug("IP 源 %s 响应无 IP 字段，换下一个源", url,
                             extra=_ev("ip_source_attempt",
                                       {"source": url, "ok": False, "error": last_err}))
                continue
            logger.debug("IP 源 %s 成功", url,
                         extra=_ev("ip_source_attempt", {"source": url, "ok": True}))
            return info
        except Exception as e:
            last_err = str(e)
            logger.debug("IP 源 %s 失败: %s", url, e,
                         extra=_ev("ip_source_attempt",
                                   {"source": url, "ok": False, "error": str(e)[:200]}))
    return {"error": last_err or "所有IP源均失败"}


async def run_ip_quality_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                               results: dict[str, TestResult]) -> None:
    """运行 IP 风控检测"""
    pbar = tqdm(total=len(nodes), desc="IP检测", unit="节点", mininterval=1.0)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    ssl_ctx = _no_verify_ssl()
    # 每次请求用独立连接，避免连接池复用导致 ipapi.is 缓存
    last_ip = None
    try:
        for node in nodes:
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 检测中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                pbar.set_postfix_str(f"{display} 切换失败", refresh=False)
                pbar.update(1)
                continue
            await asyncio.sleep(0.5)  # 给切换和 DNS 留时间
            proxy = mihomo.get_proxy_url()
            # 每次创建新 session，确保走正确的出口
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as session:
                ip_info = await check_ip_quality(session, proxy)
                if node.name in results:
                    results[node.name].ip_info = ip_info
                    # 标记 IP 是否与上一个相同
                    curr_ip = ip_info.get("ip", "")
                    if curr_ip and curr_ip == last_ip:
                        results[node.name].ip_info["same_ip_warning"] = True
                    last_ip = curr_ip if curr_ip else last_ip
                risk = ip_info.get("risk_score")
                risk = "?" if risk is None else risk
                ip_addr = ip_info.get("ip", "?")
                _log_ip_details(node.name, ip_info)
                pbar.set_postfix_str(f"{display} {ip_addr} 风险:{risk}%", refresh=False)
                pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()




# ═══════════════════════════════════════════════════════════════
#  图片生成（MiaoKo 风格）
# ═══════════════════════════════════════════════════════════════

def _get_speed_color(s: Optional[float]):
    if s is None: return (200,200,200)
    if s < 0: s = 0
    b = s * 1024 * 1024
    for i in range(len(SPEED_COLORS)-1):
        l,cl = SPEED_COLORS[i]; u,cr = SPEED_COLORS[i+1]
        if l <= b <= u:
            lev = (b-l)/(u-l)
            return tuple(int(a*(1-lev)+b*lev) for a,b in zip(cl,cr))
    return SPEED_COLORS[-1][1]


def _bar_color(sp: float) -> tuple:
    """柱状图配色（按绝对速度）：越快越绿、越慢越红，阈值间线性插值"""
    b = sp * 1024 * 1024
    ramp = [
        (0.0, (221, 51, 51)),                     # 0        → 红
        (0.5 * 1024 * 1024, (221, 102, 51)),      # 0.5MB/s  → 橙红
        (4 * 1024 * 1024, (221, 187, 0)),         # 4MB/s    → 黄
        (16 * 1024 * 1024, (119, 170, 34)),       # 16MB/s   → 黄绿
        (32 * 1024 * 1024, (34, 170, 34)),        # 32MB/s+  → 深绿
    ]
    if b <= ramp[0][0]:
        return ramp[0][1]
    for i in range(len(ramp) - 1):
        l, cl = ramp[i]
        u, cr = ramp[i + 1]
        if l <= b <= u:
            lev = 0 if u == l else (b - l) / (u - l)
            return tuple(int(a * (1 - lev) + bb * lev) for a, bb in zip(cl, cr))
    return ramp[-1][1]

def _fmt_ms(ms):
    return "超时" if ms is None else f"{ms:.0f}ms"

def _fmt_mb(s):
    return "--" if s is None else f"{s:.1f}MB/s"

def _fmt_ss(s):
    if "错误" in s:
        # 简化错误信息：只保留错误类型，去掉括号内的完整类名
        # 如 错误(ClientConnectorError) → 连接失败
        return "连接失败"
    if len(s) > 25:
        if "解锁" in s or "送中" in s: return s[:15]
        if "失败" in s: return s[:25]
    return s

def _font(size=13):
    for p in ["C:/Windows/Fonts/msyh.ttc","C:/Windows/Fonts/simhei.ttf",
              "C:/Windows/Fonts/msyhbd.ttc","/usr/share/fonts/wqy/wqy-microhei.ttc",
              "/System/Library/Fonts/PingFang.ttc"]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p,size)
            except Exception: pass
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    except Exception:
        pass
    return ImageFont.load_default()

def _ctxt(cid, r):
    if cid=="idx": return ""
    if cid=="name": return r.node.name[:24]
    if cid=="type": return r.node.type[:7]
    if cid=="ping":
        if is_udp_node(r.node): return "UDP"
        if r.tcp_ping is not None: return _fmt_ms(r.tcp_ping)
        if r.tcp_probe: return "代理可达"
        return "超时"
    if cid=="http": return _fmt_ms(r.http_latency)
    if cid=="speed": return _fmt_mb(r.speed)
    if cid=="maxspeed": return _fmt_mb(r.max_speed or r.speed)
    if cid=="ip_type":
        d=r.ip_info
        if d.get("error") or not d.get("ip"): return "--"
        if d.get("is_datacenter") is None: return "--"  # 数据源无风控字段
        if d.get("is_datacenter"): return "商宽/机房 IP"
        return "家宽 IP"
    if cid=="ip_risk":
        d=r.ip_info
        if d.get("error") or not d.get("ip"): return "--"
        sc=d.get("risk_score")
        if sc is None: return "--"  # 数据源无风控字段
        if sc<20: return f"低({sc})"
        if sc<60: return f"中({sc})"
        return f"高({sc})"
    if cid=="asn":
        asn = r.ip_info.get("asn") or ""
        org = r.ip_info.get("org") or ""
        txt = f"{asn} {org}" if asn and org else (asn or org or "--")
        return txt[:35]
    if cid=="udp": return _udp_type_text(r.node)
    return _fmt_ss(r.streaming.get(cid,""))

def sort_results(results, sort_by):
    # sort_by = "none"|"default"|"max_desc"|"max_asc"|"avg_desc"|"avg_asc"|"name_asc"|"name_desc"
    if sort_by == "none":
        return list(results)  # 保持订阅原始顺序
    if sort_by in ("default", "max_desc"):
        return sorted(results, key=lambda r: (r.max_speed is None, r.speed is None, -(r.max_speed or r.speed or 0)))
    if sort_by == "max_asc":
        return sorted(results, key=lambda r: (r.max_speed is None, r.speed is None, (r.max_speed or r.speed or 0)))
    if sort_by == "avg_desc":
        return sorted(results, key=lambda r: (r.speed is None, -(r.speed or 0)))
    if sort_by == "avg_asc":
        return sorted(results, key=lambda r: (r.speed is None, (r.speed or 0)))
    if sort_by == "name_asc":
        return sorted(results, key=lambda r: r.node.name)
    if sort_by == "name_desc":
        return sorted(results, key=lambda r: r.node.name, reverse=True)
    return sorted(results, key=lambda r: (r.max_speed is None, r.speed is None, -(r.max_speed or r.speed or 0)))

def export_results_json(results: list[TestResult], mode: str, display_mode: str = None) -> str:
    """导出测试结果为 JSON 文件（display_mode 为原始模式名，用于文件名与 mode 字段）"""
    display_mode = display_mode or mode
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fpath = os.path.join(OUTPUT_DIR, f"测速结果_{display_mode}_{ts}.json")

    data = []
    for r in results:
        entry = {
            "name": r.node.name,
            "type": r.node.type,
            "server": r.node.server,
            "port": r.node.port,
            "udp_node": is_udp_node(r.node),
            "udp_type": _udp_type_text(r.node),
            "tcp_ping_ms": r.tcp_ping,
            "tcp_probe": r.tcp_probe,
            "http_latency_ms": r.http_latency,
            "speed_mbs": r.speed,
            "max_speed_mbs": r.max_speed,
            "speed_per_sec_mbs": r.speed_per_sec,
            "streaming": r.streaming,
            "ip_info": r.ip_info,
            "error": r.error,
        }
        data.append(entry)

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump({
            "mode": display_mode,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": VERSION,
            "results": data,
        }, f, ensure_ascii=False, indent=2)
    return fpath


def generate_report_image(results, mode, total_time, sort_by="default", display_mode=None):
    """生成 PNG 报告：mode 驱动列布局，display_mode 驱动文件名与页眉"""
    display_mode = display_mode or mode
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fpath = os.path.join(OUTPUT_DIR, f"测速结果_{display_mode}_{ts}.png")
    if not results:
        img = Image.new("RGB", (800,200), "white")
        ImageDraw.Draw(img).text((50,80), "无有效节点可显示", fill="black", font=_font(16))
        img.save(fpath); return fpath

    font,fsm,flg = _font(12),_font(10),_font(13)
    has_ip = any(r.ip_info for r in results if r.ip_info)
    has_sp = any(r.streaming for r in results if r.streaming)
    stream_ids = set()
    if has_sp:
        for r in results: stream_ids.update(r.streaming.keys())
    has_http = any(r.http_latency is not None for r in results)
    has_spd = any(r.speed is not None for r in results)
    
    # ---- 列布局（按模式） ----
    if mode in ("speed", "basic"):
        cols = [("idx","#",36,"c"),("name","节点名称",210,"l"),("type","类型",72,"c"),
                ("ping","延迟RTT",84,"c"),("http","HTTP延迟",88,"c"),
                ("speed","平均速度",92,"c"),("maxspeed","最大速度",92,"c"),("speed_bar","每秒速度",80,"c"),
                ("udp","UDP类型",62,"c")]
    elif mode in ("normal","full"):
        cols = [("idx","#",34,"c"),("name","节点名称",180,"l"),("type","类型",68,"c"),
                ("ping","TLS延迟",76,"c"),("http","HTTP延迟",80,"c")]
        if has_ip:
            cols += [("ip_type","IP类型",82,"c"),("ip_risk","IP风险",72,"c")]
        # 渲染本次实际测过的全部流媒体列（COMMON 9 个或 FULL 34 个）
        name_map = {s["id"]: s["name"] for s in FULL_STREAMING_SERVICES}
        for sid in stream_ids:
            cols.append((sid, name_map.get(sid, sid), 64, "c"))
        if has_spd:
            cols += [("speed","平均速度",82,"c"),("maxspeed","最高速度",82,"c"),("speed_bar","每秒速度",72,"c")]
        if has_ip:
            cols.append(("asn","ASN",130,"l"))
        cols.append(("udp","UDP类型",58,"c"))
    elif mode == "streaming":
        # 纯流媒体模式：简洁，不显示测速相关列
        cols = [("idx","#",34,"c"),("name","节点名称",180,"l"),("type","类型",68,"c")]
        name_map = {s["id"]:s["name"] for s in FULL_STREAMING_SERVICES}
        for sid in stream_ids:
            cols.append((sid, name_map.get(sid, sid), 64, "c"))
    else:
        cols = [("idx","#",34,"c"),("name","节点名称",180,"l")]

    # 计算列宽
    cw = {}
    for cid,title,dw,_ in cols:
        w = dw
        for r in results:  # 遍历全部行估算列宽（画布上限 300 行）
            txt = _ctxt(cid,r)
            try: tw = int(font.getlength(txt)+18)
            except Exception: tw = int(max(dw-10, len(txt)*7+10))
            w = max(w,tw)
        cw[cid] = int(w)

    pad,rh,hh,fh = 14,26,40,70
    iw = sum(cw.values())
    tw = int(iw+pad*2)
    # 最多显示 300 个节点，防止图片内存溢出
    max_rows = 300
    nh = min(len(results), max_rows)
    th = int(hh + nh*rh + fh + 6)

    img = Image.new("RGB", (tw,th), (245,245,245))
    dr = ImageDraw.Draw(img)
    lg, dg = "#DDDDDD", "#888888"

    # 页眉
    mn = {"speed":"简单测速","basic":"简单测速","normal":"标准测试","full":"标准测试",
          "streaming":"流媒体","streaming_ai":"AI流媒体","streaming_all":"全部流媒体"}
    hdr = f"speed_test.py {VERSION} | {mn.get(display_mode, display_mode)}"
    dr.text((pad,6), hdr, fill="#333", font=flg)
    dr.text((pad,24), f"订阅: {len(results)} 节点 | {time.strftime('%Y-%m-%d %H:%M:%S')}", fill=dg, font=fsm)
    dr.line([(pad,hh-2),(tw-pad,hh-2)], fill=lg, width=1)

    y = hh
    # 表头
    dr.rectangle([(pad,y),(tw-pad,y+rh)], fill="#F0F0F0")
    x = pad
    for cid,ttl,_,al in cols:
        w = cw[cid]; tx = x+w/2 if al=="c" else x+6
        tw2 = dr.textlength(ttl, font=font)
        dr.text((tx-tw2/2 if al=="c" else tx, y+6), ttl, fill="#333", font=font)
        x += w
    y += rh

    # 数据
    sr = sort_results(results, sort_by)

    for idx, r in enumerate(sr[:nh]):  # 只画画布内的行，页脚才不会被顶出画布
        x = pad
        bg = "#FFF" if idx%2==0 else "#FAFAFA"
        dr.rectangle([(pad,y),(tw-pad,y+rh)], fill=bg)
        pv = r.tcp_ping
        pc = "#999" if pv is None else "#22AA22" if pv<50 else "#DDBB00" if pv<150 else "#FF8800" if pv<300 else "#DD3333"

        for cid,_,_,al in cols:
            w = cw[cid]; txt = _ctxt(cid, r); fc = "#333"
            if cid=="idx": txt=str(idx+1); fc="#666"
            elif cid=="ping": fc=pc
            elif cid=="http": 
                p=r.http_latency
                fc="#999" if p is None else "#22AA22" if p<50 else "#DDBB00" if p<150 else "#FF8800" if p<300 else "#DD3333"
            elif cid=="speed_bar":
                speeds = r.speed_per_sec
                if speeds:
                    n = len(speeds)
                    row_mx = max(speeds) if any(speeds) else 1.0
                    bar_w = max(4, (w - 6) // n - 1)
                    bars = []
                    for i, sp in enumerate(speeds):
                        # 行内相对高度：满高 = 该行自身最大秒速，行内起伏始终可见
                        bh = max(3, int((rh - 6) * sp / row_mx))
                        bx = x + 3 + int(i * (bar_w + 1))
                        bars.append((bx, bar_w, bh, sp))
                    # 第一遍：先把柱子立起来（浅灰底）
                    for bx, bw, bh, _ in bars:
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bw, y+rh-4)], fill=(200, 200, 200))
                    # 第二遍：按绝对速度上色（越快越绿、越慢越红）
                    for bx, bw, bh, sp in bars:
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bw, y+rh-4)], fill=_bar_color(sp))
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bw, y+rh-4)], outline="#666", width=1)
                elif r.speed is not None:
                    # 退化分支：单色条（行内满高 + 绝对速度配色）
                    dr.rectangle([(x+4, y+3), (x+w-4, y+rh-4)], fill=_bar_color(r.speed))
                    dr.rectangle([(x+4, y+3), (x+w-4, y+rh-4)], outline="#666", width=1)
            elif cid=="ip_risk":
                sc2 = r.ip_info.get("risk_score",0)
                fc = "#22AA22" if sc2<30 else "#DDBB00" if sc2<60 else "#DD3333"
            elif cid=="ip_type":
                di = r.ip_info
                fc = "#DD8833" if di.get("is_datacenter") else "#33AA55"
            elif cid in r.streaming:
                ds = _fmt_ss(txt); txt = ds
                fc = "#22AA22" if "解锁" in ds or "可用" in ds else "#DD3333" if "失败" in ds or "封锁" in ds or ds=="N/A" else "#999"

            if al=="c":
                tw2 = dr.textlength(txt, font=font)
                dr.text((x+(w-tw2)/2, y+5), txt, fill=fc, font=font)
            else:
                dr.text((x+8, y+5), txt, fill=fc, font=font)
            x += w
        dr.line([(pad,y+rh),(tw-pad,y+rh)], fill=lg, width=1)
        y += rh

    # 页脚（多行）
    y += 6
    tcp_ok = [r for r in results if r.tcp_ping is not None]
    succ = sum(1 for r in results if r.tcp_ping is not None or r.tcp_probe)
    avgp = sum(r.tcp_ping for r in tcp_ok) / len(tcp_ok) if tcp_ok else 0
    ftr1 = f"TCP RTT 为单次数据交换延迟，HTTP Ping 为单次请求体感延迟。"
    sort_names = {"none":"订阅顺序","default":"最大速度降序","max_desc":"最大速度降序","max_asc":"最大速度升序",
                  "avg_desc":"平均速度降序","avg_asc":"平均速度升序",
                  "name_asc":"名称A→Z","name_desc":"名称Z→A"}
    ftr2 = f"节点: {succ}/{len(results)} 可达 | 平均延迟: {avgp:.0f}ms | 测试耗时: {total_time:.0f}s"
    udp_n = sum(1 for r in results if is_udp_node(r.node))
    if udp_n:
        ftr2 += f" | UDP节点: {udp_n} 个(经HTTP实测)"
    ftr2 += f" | 排序: {sort_names.get(sort_by, sort_by)}"
    ftr3 = f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')} (CST) | Powered by speed_test.py {VERSION}"
    if len(results) > max_rows:
        ftr3 += f" | 仅显示前 {max_rows}/{len(results)} 节点"
    dr.text((pad, y), ftr1, fill=dg, font=fsm)
    dr.text((pad, y+14), ftr2, fill=dg, font=fsm)
    dr.text((pad, y+28), ftr3, fill=dg, font=fsm)
    # 调整页脚高度
    dr.rectangle([(pad,0),(tw-pad,th-1)], outline="#CCC", width=1)
    img.save(fpath)
    return fpath
# ═══════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════

def read_subscribe_urls() -> list[str]:
    """从默认文件读取订阅 URL"""
    urls = []
    if os.path.exists(SUBSCRIBE_FILE):
        with open(SUBSCRIBE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    return urls


def _finish_partial(results_dict: dict, mode: str, display_mode: str,
                    t_start: float, sort_by: str) -> str:
    """提前结束路径共用：生成 PNG + JSON 并记录路径"""
    img_path = generate_report_image(
        list(results_dict.values()), mode, time.monotonic() - t_start, sort_by,
        display_mode=display_mode,
    )
    try:
        json_path = export_results_json(list(results_dict.values()), mode,
                                        display_mode=display_mode)
    except Exception as e:
        logger.warning("JSON 导出失败: %s", e)
        json_path = ""
    logger.info(f"报告已生成: {img_path}")
    if json_path:
        logger.info(f"数据已生成: {json_path}")
    return img_path


async def _run_node_pipeline(pool: MihomoWorkerPool, node_tasks: list,
                             results_dict: dict, streaming_services: list) -> None:
    """并行流水线：pool 槽位即并发度，每个节点依次完成 流媒体→IP 后释放槽位
    （测速恒串行，不在此流水线内）"""
    queue: asyncio.Queue = asyncio.Queue()
    for t in node_tasks:
        await queue.put(t)
    for _ in pool.workers:
        await queue.put(None)  # 终止哨兵

    ssl_ctx = _no_verify_ssl()
    ip_lock = asyncio.Lock()
    seen_ips: set = set()
    last_ip_check = [0.0]  # 全局节流：免费 IP API 有限额，串行 + 最小间隔防 429

    pbar = tqdm(total=len(node_tasks), desc="节点测试", unit="节点", mininterval=1.0)

    async def worker_loop(worker: MihomoWorker):
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            node, do_stream, do_ip = item
            try:
                pbar.set_postfix_str(f"{_flag_to_text(node.name)} 加载中")
                if not await worker.load_node(node):
                    if node.name in results_dict:
                        results_dict[node.name].error = "节点加载失败"
                    continue
                proxy = worker.get_proxy_url()

                # 1) 流媒体解锁
                if do_stream:
                    await asyncio.sleep(0.3)
                    async with aiohttp.ClientSession(
                            connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
                        streaming = await check_one_node_streaming(sess, proxy, node, streaming_services)
                        if node.name in results_dict:
                            results_dict[node.name].streaming = streaming
                        unlocked = sum(1 for v in streaming.values()
                                       if "解锁" in v or "可用" in v or "成功" in v)
                        _log_streaming_details(node.name, streaming)
                        pbar.set_postfix_str(f"{_flag_to_text(node.name)} 解锁{unlocked}/{len(streaming)}")

                # 2) IP 质量（多源回退 + 全局串行节流）
                if do_ip:
                    await asyncio.sleep(0.3)
                    async with ip_lock:
                        wait = IP_CHECK_INTERVAL - (time.monotonic() - last_ip_check[0])
                        if wait > 0:
                            await asyncio.sleep(wait)
                        async with aiohttp.ClientSession(
                                connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
                            ip_info = await check_ip_quality(sess, proxy)
                        last_ip_check[0] = time.monotonic()
                        if node.name in results_dict:
                            results_dict[node.name].ip_info = ip_info
                            curr_ip = ip_info.get("ip", "")
                            if curr_ip:
                                if curr_ip in seen_ips:
                                    results_dict[node.name].ip_info["same_ip_warning"] = True
                                seen_ips.add(curr_ip)
                        risk = ip_info.get("risk_score")
                        risk = "?" if risk is None else risk
                        _log_ip_details(node.name, ip_info)
                        pbar.set_postfix_str(f"{_flag_to_text(node.name)} 风险:{risk}%")
            except Exception as e:
                if node.name in results_dict:
                    results_dict[node.name].error = str(e)
                logger.debug("节点 %s 流水线异常: %s", node.name, e)
            finally:
                queue.task_done()
                pbar.update(1)

    try:
        await asyncio.gather(*[worker_loop(w) for w in pool.workers])
    finally:
        pbar.close()


async def run_test(subscribe_url, mode: str = "basic", sort_by: str = "default",
                   fast: bool = False, workers: int = DEFAULT_WORKERS) -> str:
    """运行完整测试流程（subscribe_url 支持单个 URL 或 URL 列表）"""
    global SPEED_WINDOW_SECONDS
    t_start = time.monotonic()
    output_mode = mode  # 保留原始模式名（streaming_ai/streaming_all），供文件名/报告头/JSON
    phase = "初始化"  # 当前阶段（中断事件记录用）
    new_run_log()
    logger.info(
        "运行开始: 模式=%s workers=%s fast=%s",
        output_mode, workers, fast,
        extra=_ev("run_start", {
            "version": VERSION,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "argv": list(sys.argv),
            "mode": output_mode,
            "workers": workers,
            "fast": fast,
            "deps": {
                "aiohttp": _pkg_version("aiohttp"),
                "yaml": _pkg_version("PyYAML"),
                "PIL": _pkg_version("Pillow"),
                "tqdm": _pkg_version("tqdm"),
                "requests": _pkg_version("requests"),
                "cloudscraper": HAS_CLOUDSCRAPER,
                "yt_dlp": HAS_YTDLP,
            },
        }),
    )

    # Step 1: 解析订阅
    if isinstance(subscribe_url, (list, tuple)):
        urls = [u for u in subscribe_url if u]
        if not urls:
            logger.error("订阅 URL 列表为空")
            return ""
    else:
        urls = [subscribe_url]
    logger.info("=" * 50)
    logger.info("解析订阅: %s", " | ".join(_mask_url(u) for u in urls))
    logger.info("=" * 50)
    try:
        nodes = parse_subscription_urls(urls) if len(urls) > 1 else parse_subscription_url(urls[0])
    except Exception as e:
        logger.error(f"订阅解析失败: {e}")
        return ""

    if not nodes:
        logger.error("未解析到任何节点")
        logger.error("  - 可能原因：订阅链接无效、已过期、或仅包含信息节点(127.0.0.1)")
        logger.error("  - 请检查 代理.txt 中的订阅链接是否正确")
        return ""

    type_counts = {}
    for n in nodes:
        type_counts[n.type] = type_counts.get(n.type, 0) + 1
    logger.info(
        "[成功] 解析到 %d 个节点", len(nodes),
        extra=_ev("parse_done", {"total": len(nodes), "type_counts": type_counts}),
    )
    for n in nodes[:5]:
        logger.info(f"   - {n.name} ({n.type}://{n.server}:{n.port})")
    if len(nodes) > 5:
        logger.info(f"   ... 还有 {len(nodes) - 5} 个节点")

    # 初始化结果
    results_dict: dict[str, TestResult] = {}
    for n in nodes:
        results_dict[n.name] = TestResult(node=n)

    # 模式别名
    streaming_services = None
    if mode == "speed":
        mode = "basic"
    elif mode == "normal":
        mode = "full"
        streaming_services = COMMON_STREAMING_SERVICES
    elif mode == "streaming_ai":
        mode = "streaming"
        streaming_services = AI_STREAMING_SERVICES
    elif mode == "streaming_all":
        mode = "streaming"

    # --fast：缩短测速窗口（默认 8s → 5s）
    SPEED_WINDOW_SECONDS = SPEED_WINDOW_FAST_SECONDS if fast else SPEED_WINDOW_DEFAULT_SECONDS

    # 计算步骤数
    steps = []
    if mode != "streaming":
        steps.append("TCP检测")
        steps.append("HTTP测速")
    if mode != "basic":
        steps.append("流媒体/IP检测")
    step_idx = 1

    # 阶段1: TCP 检测（来源A 直连 + 来源B mihomo 隧道并发探测）
    tcp_results = {}
    probe_results = {}
    probe_ok = 0
    success_tcp = 0
    mihomo = MihomoEngine()  # 提前创建：隧道探测与测速阶段共用内核
    pool = None
    used_pool = False
    try:
        if mode != "streaming":
            phase = "TCP检测"
            logger.info("=" * 50)
            logger.info(f"[{step_idx}/{len(steps)}] TCP Ping 延迟测试")
            logger.info("=" * 50)
            tcp_results = await run_tcp_ping(nodes)
            for name, latency in tcp_results.items():
                if name in results_dict:
                    results_dict[name].tcp_ping = latency
            success_tcp = sum(1 for v in tcp_results.values() if v is not None)

            # 来源B：直连超时节点 + UDP 节点 → mihomo 隧道并发探测
            candidates = [n for n in nodes if tcp_results.get(n.name) is None]
            if candidates and mihomo.binary_path and os.path.isfile(mihomo.binary_path):
                n_conc = min(TCP_PROBE_CONCURRENCY, len(candidates))
                logger.info(f"TCP 直连未通 {len(candidates)} 个，启动 mihomo 隧道探测（并发 {n_conc} 路）...")
                probe_results = await run_tcp_probe_pool(mihomo.binary_path, candidates)
                for name, ok in probe_results.items():
                    if name in results_dict:
                        results_dict[name].tcp_probe = ok
                if probe_results:
                    probe_ok = sum(1 for v in probe_results.values() if v)
                    logger.info(f"隧道探测: {probe_ok}/{len(candidates)} 节点可达")
                else:
                    logger.warning("隧道探测不可用（探测池启动失败），按直连结果继续")

            udp_n = sum(1 for n in nodes if is_udp_node(n))
            extra = f"（UDP节点 {udp_n} 个经隧道探测）" if udp_n else ""
            logger.info(f"TCP 检测完成: 直连 {success_tcp}/{len(nodes)} 可达{extra}")
            step_idx += 1

        # 可达性合并：直连成功 或 隧道探测成功（探测池不可用时 UDP 节点按直连语义保留）
        reachable = {name for name, v in tcp_results.items() if v is not None}
        if probe_results:
            reachable |= {name for name, v in probe_results.items() if v}
        else:
            reachable |= {n.name for n in nodes if is_udp_node(n)}
        active_speed = [n for n in nodes if n.name in reachable] if mode != "streaming" else nodes
        active_all = nodes  # 流媒体和 IP 检测用全部节点

        if mode != "streaming" and not active_speed:
            logger.error("无可用的节点，跳过后续测试")
            return _finish_partial(results_dict, mode, output_mode, t_start, sort_by)

        logger.info("启动 mihomo 引擎...")
        logger.info("=" * 50)
        binary_ok = bool(mihomo.binary_path and os.path.isfile(mihomo.binary_path))
        if not binary_ok:
            logger.error("mihomo 不可用，跳过 HTTP 测速及后续测试")
            return _finish_partial(results_dict, mode, output_mode, t_start, sort_by)

        # 阶段2: HTTP 测速（恒串行：单节点单时刻；节点内部 DOWNLOAD_CONNS 路并发连接）
        if mode != "streaming" and active_speed:
            phase = "HTTP测速"
            yt_url = resolve_youtube_download_url(timeout=10)
            yt_method = "direct"
            mihomo.generate_config(active_all)
            await mihomo.start()
            logger.info("mihomo 启动成功",
                        extra=_ev("mihomo_start", {"api_port": mihomo.api_port,
                                                   "mixed_port": mihomo.mixed_port}))
            if not yt_url and active_speed:
                # 本机直连失败 → 经首个可达节点隧道再试（节点能访问油管是使用该源的前提）
                ok = await mihomo.switch_proxy(active_speed[0].name)
                if ok:
                    await asyncio.sleep(0.3)
                    yt_url = resolve_youtube_download_url(proxy=mihomo.get_proxy_url())
                    yt_method = "node_proxy"
            if yt_url:
                logger.info(
                    "油管测速源就绪: %s", urlparse(yt_url).netloc,
                    extra=_ev("yt_source_resolve",
                              {"method": yt_method, "host": urlparse(yt_url).netloc}))
            else:
                logger.warning(
                    "油管测速源不可用，使用 %d 个基础源", len(SPEED_TEST_URLS),
                    extra=_ev("yt_source_resolve", {"method": yt_method, "host": None}))
            logger.info("=" * 50)
            logger.info(f"[{step_idx}/{len(steps)}] HTTP 测速（串行，{DOWNLOAD_CONNS} 连接/节点）")
            logger.info("=" * 50)
            await run_speed_test(mihomo, active_speed, results_dict)
            step_idx += 1

        # 阶段3(补测): 测速完成后，对仍超时的节点重新测 TCP（直连 + 隧道），恢复的补测速
        if mode != "streaming":
            phase = "补测超时节点"
            timeout_nodes = [n for n in nodes
                             if n.name in results_dict
                             and results_dict[n.name].tcp_ping is None
                             and results_dict[n.name].tcp_probe is not True]
            if timeout_nodes:
                logger.info("=" * 50)
                logger.info(f"补测超时节点: {len(timeout_nodes)} 个（直连重试 + 隧道重试）")
                logger.info("=" * 50)
                revived = set()
                # 直连重试（UDP 节点由 run_tcp_ping 自动跳过，交给隧道重试）
                retry_tcp = await run_tcp_ping(timeout_nodes)
                for n in timeout_nodes:
                    v = retry_tcp.get(n.name)
                    if v is not None and n.name in results_dict:
                        results_dict[n.name].tcp_ping = v
                        revived.add(n.name)
                # 隧道重试
                still_dead = [n for n in timeout_nodes if retry_tcp.get(n.name) is None]
                if still_dead and mihomo.binary_path and os.path.isfile(mihomo.binary_path):
                    retry_probe = await run_tcp_probe_pool(mihomo.binary_path, still_dead)
                    for n in still_dead:
                        ok = retry_probe.get(n.name)
                        if ok is not None and n.name in results_dict:
                            results_dict[n.name].tcp_probe = ok
                            if ok:
                                revived.add(n.name)
                # 新恢复的节点补跑测速（不在原测速队列中的才补）
                to_test = [n for n in timeout_nodes
                           if n.name in revived and n.name not in {x.name for x in active_speed}]
                if to_test:
                    logger.info(
                        f"补测恢复 {len(to_test)} 个节点，补跑测速...",
                        extra=_ev("retest_speed", {"nodes": [n.name for n in to_test]}))
                    await run_speed_test(mihomo, to_test, results_dict)
                still_dead_n = sum(
                    1 for n in timeout_nodes
                    if results_dict[n.name].tcp_ping is None
                    and results_dict[n.name].tcp_probe is not True)
                logger.info(
                    f"补测完成: 恢复 {len(revived)} 个，仍超时 {still_dead_n} 个",
                    extra=_ev("retest_done", {"revived": sorted(revived),
                                              "still_dead": still_dead_n}))

        # 阶段4: 流媒体 + IP（默认 4 路并行，--workers 可调）
        phase = "流媒体/IP检测"
        need_stream = mode != "basic"
        need_ip = (mode == "full") and not fast
        if need_stream or need_ip:
            node_tasks = [(n, need_stream, need_ip) for n in active_all]
            if workers > 1:
                pool = MihomoWorkerPool(mihomo.binary_path, workers)
                if await pool.start():
                    used_pool = True
                    logger.info(
                        f"mihomo 并行池就绪: {len(pool.workers)} workers（流媒体/IP）",
                        extra=_ev("worker_pool_start", {"workers": len(pool.workers)}))
                    logger.info("=" * 50)
                    logger.info(f"[{step_idx}/{len(steps)}] 流媒体/IP 检测（并行 {len(pool.workers)} 路）")
                    logger.info("=" * 50)
                    await _run_node_pipeline(pool, node_tasks, results_dict, streaming_services)
                else:
                    logger.warning("并行池不可用，回退串行模式")

            if not used_pool:
                # 串行路径：引擎可能尚未启动（流媒体-only 模式）
                if not mihomo.process:
                    mihomo.generate_config(active_all)
                    await mihomo.start()
                logger.info("=" * 50)
                logger.info(f"[{step_idx}/{len(steps)}] 流媒体/IP 检测（串行）")
                logger.info("=" * 50)
                if need_stream:
                    await run_streaming_test(mihomo, active_all, results_dict, streaming_services)
                if need_ip:
                    await run_ip_quality_test(mihomo, active_all, results_dict)
            step_idx += 1

    except KeyboardInterrupt:
        logger.warning("用户中断测试，正在生成当前结果...（中断阶段: %s）", phase,
                       extra=_ev("user_interrupt", {"phase": phase}))
    except asyncio.CancelledError:
        # asyncio.run 下 Ctrl+C 以 CancelledError 抛出，吞掉后继续生成部分结果
        logger.warning("用户中断测试，正在生成当前结果...（中断阶段: %s）", phase,
                       extra=_ev("user_interrupt", {"phase": phase}))
    except Exception:
        logger.exception("mihomo 测试异常", extra=_ev("run_exception", {"phase": phase}))
    finally:
        if pool:
            await pool.stop()
        await mihomo.stop()
        logger.info("mihomo 已停止", extra=_ev("mihomo_stop", {}))

    # Step 7: 生成报告
    phase = "生成报告"
    total_time = time.monotonic() - t_start
    logger.info("=" * 50)
    logger.info("生成报告...")
    logger.info("=" * 50)
    img_path = generate_report_image(
        list(results_dict.values()), mode, total_time, sort_by,
        display_mode=output_mode,
    )
    logger.info("=" * 50)
    logger.info(
        "测试完成! 耗时 %.0f 秒 节点 %d 总", total_time, len(nodes),
        extra=_ev("run_end", {
            "total_seconds": round(total_time, 1),
            "nodes": len(nodes),
            "mode": output_mode,
            "report": img_path,
        }),
    )
    if mode != "streaming":
        direct_ok = sum(1 for r in results_dict.values() if r.tcp_ping is not None)
        probe_only = sum(1 for r in results_dict.values() if r.tcp_ping is None and r.tcp_probe)
        reach_msg = f"可达: 直连 {direct_ok}/{len(nodes)}"
        if probe_only:
            reach_msg += f" + 隧道 {probe_only}"
        logger.info(reach_msg)
    unlocked = sum(
        1 for r in results_dict.values()
        if any("解锁" in v or "可用" in v for v in r.streaming.values())
    ) if any(r.streaming for r in results_dict.values()) else -1
    if unlocked >= 0:
        logger.info(f"流媒体解锁节点: {unlocked}/{len(nodes)}")
    # 同时导出 JSON
    try:
        json_path = export_results_json(list(results_dict.values()), mode,
                                        display_mode=output_mode)
    except Exception:
        logger.exception("JSON 导出失败")
        json_path = ""

    logger.info(f"报告: {img_path}", extra=_ev("report_done", {"path": img_path}))
    if json_path:
        logger.info(f"数据: {json_path}", extra=_ev("json_export_done", {"path": json_path}))
    if _LOG_FILE:
        logger.info(f"日志: {_LOG_FILE}")
    logger.info("=" * 50)
    return img_path


def _str_width(s: str) -> int:
    """计算字符串在终端中的显示宽度（中文/全角=2，英文/半角=1）"""
    w = 0
    for c in s:
        cp = ord(c)
        if 0x2500 <= cp <= 0x257F:
            w += 1  # 方框绘图字符是半角
        elif cp > 127:
            w += 2  # CJK 等全角字符
        else:
            w += 1
    return w


def _pad_right(text: str, width: int) -> str:
    """在文本右侧填充空格到指定显示宽度"""
    return text + " " * max(0, width - _str_width(text))


def _open_report(path: str) -> bool:
    """打开报告文件（os.startfile；失败或非 Windows 时记录错误，不崩溃）"""
    try:
        os.startfile(path)
        return True
    except Exception as e:
        logger.error(f"打开报告失败: {path} ({e})")
        return False


def show_menu():
    """显示交互菜单"""
    subprocess.call("cls" if sys.platform == "win32" else "clear", shell=True)
    print("╔════════════════════════════════╗")
    # 菜单每行内容宽度（不含边框）固定为 32 个字符宽度
    title = "机场测速工具 " + VERSION
    title_pad = 32 - _str_width(title)
    print(f"║{' ' * (title_pad // 2)}{title}{' ' * (title_pad - title_pad // 2)}║")
    print("╠════════════════════════════════╣")
    print(f"║ {_pad_right('1. 简单测速', 31)}║")
    print(f"║ {_pad_right('2. 标准测试', 31)}║")
    print(f"║ {_pad_right('3. AI流媒体', 31)}║")
    print(f"║ {_pad_right('4. 全部流媒体', 31)}║")
    print(f"║ {_pad_right('5. 查看上次结果', 31)}║")
    print(f"║ {_pad_right('6. 更新 mihomo 内核', 31)}║")
    print(f"║ {_pad_right('7. 退出', 31)}║")
    print("╚════════════════════════════════╝")


async def async_main():
    """异步主入口"""
    # 检查参数
    args = sys.argv[1:]

    # 直接传参模式
    show_menu_mode = False
    if args:
        url = None
        mode = "basic"
        fast = False
        workers = DEFAULT_WORKERS
        for i, arg in enumerate(args):
            if arg == "--full":
                mode = "full"
            elif arg == "--fast":
                fast = True
            elif arg.startswith("--workers="):
                try:
                    workers = max(1, min(int(arg.split("=", 1)[1]), MAX_WORKERS))
                except ValueError:
                    logger.warning("--workers 参数无效: %s，使用默认值 %d", arg, DEFAULT_WORKERS)
            elif arg == "--workers":
                if i + 1 >= len(args):
                    logger.warning("--workers 缺少参数，使用默认值 %d", DEFAULT_WORKERS)
                else:
                    try:
                        workers = max(1, min(int(args[i + 1]), MAX_WORKERS))
                    except ValueError:
                        logger.warning("--workers 参数无效: %s，使用默认值", args[i + 1])
            elif arg == "--help" or arg == "-h":
                print("用法:")
                print("  python speed_test.py                    交互菜单")
                print("  python speed_test.py <订阅URL>          轻量测速")
                print("  python speed_test.py <URL> --full       完整测速")
                print("  python speed_test.py <URL> --fast       快速模式(5s窗口/跳过IP检测)")
                print("  python speed_test.py <URL> --workers N  流媒体/IP并行数(1-8,默认4;测速恒串行)")
                print("  python speed_test.py -i file.txt        从文件读URL")
                print("  python speed_test.py --menu             显示菜单")
                print("  python speed_test.py --report           打开上次报告")
                return
            elif arg == "--report":
                # 查找最新的 PNG 报告并打开
                if os.path.exists(OUTPUT_DIR):
                    pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
                    if pngs:
                        latest = max(pngs, key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)))
                        latest_path = os.path.join(OUTPUT_DIR, latest)
                        logger.info(f"打开最新报告: {latest_path}")
                        _open_report(latest_path)
                    else:
                        logger.error("output 目录中没有 PNG 报告")
                else:
                    logger.error("output 目录不存在")
                return
            elif arg == "--menu":
                show_menu_mode = True
                break
            elif arg.startswith("http://") or arg.startswith("https://"):
                url = arg
            elif arg == "-i" and i + 1 < len(args):
                filepath = args[i + 1]
                if os.path.exists(filepath):
                    url_list = []
                    with open(filepath, "r", encoding="utf-8") as f:
                        for line in f:
                            l = line.strip()
                            if l and not l.startswith("#"):
                                url_list.append(l)
                    url = url_list  # 支持多 URL 合并解析
                else:
                    logger.error("文件不存在: %s", filepath)
        if url and not show_menu_mode:
            await run_test(url, mode, fast=fast, workers=workers)
            return

    # 交互菜单模式
    last_result_path = ""
    while True:
        show_menu()
        choice = input("\n请选择 [1-7]: ").strip()
        logger.debug("菜单选择: %s", choice, extra=_ev("menu_choice", {"choice": choice}))

        if choice in ("1", "2", "3", "4"):
            urls = read_subscribe_urls()
            if not urls:
                manual = input("未找到 代理.txt，请输入订阅URL: ").strip()
                logger.debug(
                    "手动输入订阅URL",
                    extra=_ev("manual_subscribe_input",
                              {"url": _mask_url(manual) if manual else ""}))
                if manual:
                    urls = [manual]
                else:
                    continue
            mode_map = {"1": "speed", "2": "normal", "3": "streaming_ai", "4": "streaming_all"}
            mode = mode_map.get(choice, "speed")

            print("\n排序方式：")
            print("  1. 订阅顺序")
            print("  2. 最大速度 降序 ⬅ 默认")
            print("  3. 最大速度 升序")
            print("  4. 平均速度 降序")
            print("  5. 平均速度 升序")
            print("  6. 节点名 A→Z")
            print("  7. 节点名 Z→A")
            sort_choice = input("请选择 [1-7] (默认2): ").strip()
            sort_map = {"1": "none", "2": "max_desc", "3": "max_asc",
                        "4": "avg_desc", "5": "avg_asc",
                        "6": "name_asc", "7": "name_desc"}
            sort_by = sort_map.get(sort_choice, "max_desc")

            last_result_path = await run_test(urls, mode, sort_by)
            input("\n按 Enter 返回菜单...")

        elif choice == "5":
            # 优先打开本次会话生成的结果；否则回退扫描 output 目录最新 PNG
            target = last_result_path if last_result_path and os.path.exists(last_result_path) else ""
            if not target and os.path.exists(OUTPUT_DIR):
                pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
                if pngs:
                    latest = max(pngs, key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)))
                    target = os.path.join(OUTPUT_DIR, latest)
            if target:
                _open_report(target)
            else:
                print("暂无结果文件")
            input("\n按 Enter 返回菜单...")

        elif choice == "6":
            print("正在更新 mihomo 内核...")
            try:
                tmp_dir = tempfile.mkdtemp(prefix="mihomo_update_")
                binary = MihomoEngine._download_mihomo(target_dir=tmp_dir)
                if binary:
                    # 下载成功后才替换旧内核（原子替换，失败保留旧版）
                    if os.path.exists(MIHOMO_DIR):
                        shutil.rmtree(MIHOMO_DIR)
                    os.makedirs(MIHOMO_DIR, exist_ok=True)
                    dst = os.path.join(MIHOMO_DIR, os.path.basename(binary))
                    shutil.move(binary, dst)
                    logger.info(f"mihomo 更新完成: {dst}",
                                extra=_ev("mihomo_update", {"ok": True, "path": dst}))
                    print(f"[OK] 更新完成: {dst}")
                else:
                    logger.error("mihomo 更新失败（下载或解压失败）",
                                 extra=_ev("mihomo_update", {"ok": False, "error": "download/unzip"}))
                    print("[错误] 更新失败")
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"mihomo 更新失败: {e}",
                             extra=_ev("mihomo_update", {"ok": False, "error": str(e)[:200]}))
                print(f"[错误] 更新失败: {e}")
            input("\n按 Enter 返回菜单...")

        elif choice == "7":
            print("再见!")
            break

        else:
            print("无效选择")
            logger.warning("无效菜单选择: %s", choice,
                           extra=_ev("invalid_input", {"choice": choice}))
            input("\n按 Enter 继续...")


def main():
    """同步入口"""
    setup_logging()
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("再见!")
    except asyncio.CancelledError:
        logger.info("再见!")
    except Exception:
        logger.exception("程序异常退出", extra=_ev("run_exception", {"phase": "main"}))


if __name__ == "__main__":
    main()