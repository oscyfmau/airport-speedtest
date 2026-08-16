#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据类与节点类型判定"""
from dataclasses import dataclass, field
from typing import Optional

from .config import *

@dataclass
class ProxyNode:
    name: str
    type: str          # ss/vmess/trojan/...
    server: str
    port: int
    extra: dict = field(default_factory=dict)
    sub_index: Optional[int] = None  # 订阅序号（v4.29.0 预留透传，v4.31 分组对比使用；0=第一份订阅）

    def to_clash_proxy(self) -> dict:
        """转换为 Clash YAML 代理配置"""
        proxy = {"name": self.name, "type": self.type, "server": self.server, "port": self.port}
        proxy.update(self.extra)
        return proxy


@dataclass
class TestResult:
    node: ProxyNode
    tcp_ping: Optional[float] = None
    tcp_loss: Optional[int] = None   # TCP 握手失败次数（丢包/不可达计数；UDP节点=None）
    tcp_probe: Optional[bool] = None   # 来源B：mihomo 隧道探测（None=未探测）
    http_latency: Optional[float] = None
    speed: Optional[float] = None       # MB/s 平均速度
    max_speed: Optional[float] = None   # MB/s 峰值速度
    speed_per_sec: list = field(default_factory=list)  # 每秒速度数组
    streaming: dict = field(default_factory=dict)
    ip_info: dict = field(default_factory=dict)
    webpage: dict = field(default_factory=dict)  # 网页模拟测速：{站点: 耗时ms, avg_ms}
    error: Optional[str] = None


def is_udp_node(node: ProxyNode) -> bool:
    """判定节点是否走 UDP 传输：UDP 系协议，或 vmess/vless 的 kcp/quic 传输层"""
    return node.type in UDP_TYPES or node.extra.get("network") in ("kcp", "quic")


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

__all__ = ['ProxyNode', 'TestResult', 'is_udp_node', '_udp_type_text']
