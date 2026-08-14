#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试执行器模块"""
from .speed_test import (
    test_node_speed, run_speed_test,
    check_youtube, check_netflix, check_disney, check_chatgpt,
    check_generic, check_bilibili, check_bilibili_tw,
    check_tiktok, check_spotify, check_steam, check_primevideo, check_max,
    check_one_node_streaming,
    run_streaming_test, check_ip_quality, run_ip_quality_test,
    check_one_node_webpage, run_webpage_test, _mark_reuse,
    CORE_STREAMING_SERVICES, STANDARD_STREAMING_SERVICES,
    FULL_STREAMING_SERVICES, AI_STREAMING_SERVICES,
    SIMPLE_STREAMING_SERVICES, COMMON_STREAMING_SERVICES,
    STREAMING_CHECKERS
)
