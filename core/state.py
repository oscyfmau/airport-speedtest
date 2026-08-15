#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时可变全局状态（跨模块共享；每次测试运行前由 runner 重置）"""
from .config import *

SPEED_WINDOW_SECONDS = SPEED_WINDOW_DEFAULT_SECONDS  # 运行时全局（--fast 会改写）


_YOUTUBE_DL_URL = None  # 运行时缓存：解析成功后追加到测速源列表


_RUN_BYTES = 0          # 本次运行累计下载字节（测速阶段统计）


_SUB_INFO: dict = {}    # {订阅URL: {"download": 字节, ...}}（解析阶段捕获）


_RATE_INFO: dict = {}   # {订阅URL: 倍率}（Step 7 计算，报告页脚展示）


def reset_run_state() -> None:
    """每次测试运行前重置运行时全局状态：
    - _YOUTUBE_DL_URL：防止菜单连续运行复用上一次的 googlevideo 签名 URL（约 6h 过期）
    - _RUN_BYTES：流量倍率统计基准
    - _SUB_INFO：菜单多次运行时重新捕获订阅流量信息
    - _RATE_INFO：流量倍率结果
    - SPEED_WINDOW_SECONDS：--fast 会改写，重置回默认
    """
    global SPEED_WINDOW_SECONDS, _YOUTUBE_DL_URL, _RUN_BYTES, _SUB_INFO, _RATE_INFO
    SPEED_WINDOW_SECONDS = SPEED_WINDOW_DEFAULT_SECONDS
    _YOUTUBE_DL_URL = None
    _RUN_BYTES = 0
    _SUB_INFO = {}
    _RATE_INFO = {}

__all__ = ['SPEED_WINDOW_SECONDS', '_YOUTUBE_DL_URL', '_RUN_BYTES', '_SUB_INFO', '_RATE_INFO']
