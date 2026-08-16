#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机场测速工具 v4.27.0 —— 入口与兼容重导出

v4.10 起全部逻辑按模块拆分：
  core/config.py          常量（单一数据源）
  core/models.py          数据类与节点类型判定
  core/utils.py           通用工具（URL 遮蔽/编码/SSL/显示宽度/可选依赖）
  core/logging_setup.py   日志系统（控制台 + JSONL）
  core/procs.py           mihomo 子进程登记与兜底终止
  core/state.py           运行时可变全局状态
  core/parser.py          订阅解析器
  core/engine.py          mihomo 引擎 + TCP 直连检测
  core/tester.py          HTTP 测速执行器
  core/streaming.py       流媒体解锁检测
  core/ip_quality.py      IP 质量检测
  core/webpage.py         网页模拟测速
  core/report.py          PNG 报告与 JSON 导出
  core/runner.py          测试流程编排
  core/cli.py             命令行入口与菜单

本文件保留全部旧符号：`from core.speed_test import X` 与 `from core import X` 继续可用。
"""
import os
import sys

# 直接运行 python core/speed_test.py 时，项目根不在 sys.path（脚本目录为 core/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cli import main, async_main, show_menu, _open_report
from core.config import *
from core.engine import *
from core.ip_quality import *
from core.logging_setup import *
from core.models import *
from core.parser import *
from core.procs import *
from core.report import *
from core.runner import *
from core.settings import *
from core.state import *
from core.streaming import *
from core.tester import *
from core.utils import *
from core.webpage import *

__all__ = [
    # 常量
    "VERSION", "MIHOMO_REPO", "MIHOMO_DIR", "OUTPUT_DIR", "LOG_DIR",
    "SUBSCRIBE_FILE",
    "TCP_PING_CONCURRENCY", "HTTP_LATENCY_TIMEOUT", "HTTP_DOWNLOAD_TIMEOUT",
    "STREAMING_TEST_TIMEOUT", "IP_QUALITY_TIMEOUT", "WPS_INTERNATIONAL_URLS",
    "WPS_CN_URLS", "DEFAULT_WORKERS", "MAX_WORKERS", "TCP_PROBE_CONCURRENCY",
    "TCP_PROBE_TIMEOUT", "SPEED_WINDOW_DEFAULT_SECONDS",
    "SPEED_WINDOW_FAST_SECONDS", "SPEED_WINDOW_SECONDS", "MIN_SPEED_BYTES",
    "DOWNLOAD_CONNS", "SLOW_ABORT_SECONDS", "SLOW_ABORT_BYTES",
    "SPEED_TEST_URLS", "YOUTUBE_VIDEO_IDS", "YOUTUBE_SOURCE_ENABLED",
    "IP_CHECK_INTERVAL", "UDP_TYPES", "SPEED_COLORS",
    "CORE_STREAMING_SERVICES", "STANDARD_STREAMING_SERVICES",
    "FULL_STREAMING_SERVICES", "AI_STREAMING_SERVICES",
    "SIMPLE_STREAMING_SERVICES", "COMMON_STREAMING_SERVICES",
    "STREAMING_CHECKERS", "IP_SOURCES", "PARSERS", "MIHOMO_SUPPORTED_TYPES",
    "BILI_TW_EP_IDS", "URI_PATTERN",
    # 数据类
    "ProxyNode", "TestResult",
    # 日志
    "logger", "setup_logging", "new_run_log", "JsonlFileHandler",
    # 工具
    "HAS_CLOUDSCRAPER", "HAS_YTDLP", "is_udp_node", "b64decode_pad",
    # 解析器
    "parse_vmess", "parse_vless", "parse_trojan", "parse_ss", "parse_ssr",
    "parse_hysteria2", "parse_hysteria", "parse_tuic", "parse_anytls",
    "parse_wireguard", "parse_naive", "parse_shadowtls", "parse_juicity",
    "parse_ssh", "parse_socks", "parse_http", "parse_node_uri",
    "parse_subscription_url", "parse_subscription_urls",
    "parse_subscription_content", "detect_and_decode", "read_subscribe_urls",
    "resolve_youtube_download_url",
    # 引擎与 TCP 检测
    "MihomoEngine", "MihomoWorker", "MihomoWorkerPool",
    "tcp_ping", "tcp_ping_retry", "run_tcp_ping", "run_tcp_probe_pool",
    # 测速
    "test_node_speed", "run_speed_test",
    # 流媒体 / IP / 网页
    "check_youtube", "check_netflix", "check_disney", "check_chatgpt",
    "check_generic", "check_bilibili", "check_bilibili_tw", "check_tiktok",
    "check_spotify", "check_steam", "check_primevideo", "check_max",
    "check_one_node_streaming", "run_streaming_test",
    "check_ip_quality", "run_ip_quality_test",
    "check_one_node_webpage", "run_webpage_test",
    # 报告
    "generate_report_image", "export_results_json", "sort_results",
    "print_console_summary",
    # 设置
    "SETTINGS_FILE", "DEFAULTS", "load_settings", "save_settings",
    "reset_settings", "update_settings", "invalidate_cache",
    # 编排与入口
    "run_test", "show_menu", "async_main", "main",
]

if __name__ == "__main__":
    main()
