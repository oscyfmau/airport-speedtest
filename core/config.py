#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置与常量（单一数据源；v4.10 起为真定义模块）"""
import os

VERSION = "4.25.0"  # SemVer：主版本.次版本.修订号


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


_STREAM_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

__all__ = ['VERSION', 'MIHOMO_REPO', '_SCRIPT_DIR', '_BASE_DIR', 'MIHOMO_DIR', 'OUTPUT_DIR', 'LOG_DIR', 'SUBSCRIBE_FILE', 'TCP_PING_CONCURRENCY', 'HTTP_LATENCY_TIMEOUT', 'HTTP_DOWNLOAD_TIMEOUT', 'STREAMING_TEST_TIMEOUT', 'IP_QUALITY_TIMEOUT', 'WPS_INTERNATIONAL_URLS', 'WPS_CN_URLS', 'DEFAULT_WORKERS', 'MAX_WORKERS', 'TCP_PROBE_CONCURRENCY', 'TCP_PROBE_TIMEOUT', 'SPEED_WINDOW_DEFAULT_SECONDS', 'SPEED_WINDOW_FAST_SECONDS', 'MIN_SPEED_BYTES', 'DOWNLOAD_CONNS', 'SLOW_ABORT_SECONDS', 'SLOW_ABORT_BYTES', 'SPEED_TEST_URLS', 'YOUTUBE_VIDEO_IDS', 'YOUTUBE_SOURCE_ENABLED', 'IP_CHECK_INTERVAL', 'UDP_TYPES', 'SPEED_COLORS', 'CORE_STREAMING_SERVICES', 'STANDARD_STREAMING_SERVICES', 'FULL_STREAMING_SERVICES', 'AI_STREAMING_SERVICES', 'SIMPLE_STREAMING_SERVICES', '_COMMON_IDS', 'COMMON_STREAMING_SERVICES', '_STREAM_UA']
