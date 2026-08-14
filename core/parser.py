#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅解析器模块"""
from .speed_test import (
    parse_vmess, parse_vless, parse_trojan, parse_ss, parse_ssr,
    parse_hysteria2, parse_hysteria, parse_tuic, parse_anytls,
    parse_wireguard, parse_naive, parse_shadowtls, parse_juicity, parse_ssh,
    parse_socks, parse_http, parse_node_uri, parse_subscription_url,
    parse_subscription_content, detect_and_decode,
    read_subscribe_urls, PARSERS
)
