#!/usr/bin/env python3
"""报告生成：PNG 可视化 / JSON 导出 / 排序 / 格式化"""

# v4.44.0：注解延迟求值——文件里允许写 PEP 604 的 `X | None`，
# 同时继续兼容项目声明支持的 Python 3.9（不加这行，3.9 导入时 def 就会 TypeError）
from __future__ import annotations

import json
import math
import os
import time

from PIL import Image, ImageDraw, ImageFont

from .config import *
from .logging_setup import *
from .models import *
from .utils import *


def _get_speed_color(s: float | None):
    """历史接口保留（v4.32.0 起报告改走 `_speed_color`，本函数不再被调用；勿删，外部可能引用）"""
    if s is None:
        return (200, 200, 200)
    if s < 0:
        s = 0
    b = s * 1024 * 1024
    for i in range(len(SPEED_COLORS) - 1):
        l, cl = SPEED_COLORS[i]
        u, cr = SPEED_COLORS[i + 1]
        if l <= b <= u:
            lev = (b - l) / (u - l)
            return tuple(int(a * (1 - lev) + b * lev) for a, b in zip(cl, cr))
    return SPEED_COLORS[-1][1]


def _bar_color(sp: float) -> tuple:
    """柱状图配色（绝对速度分档，v4.25.0 起 = SSRSpeedN v1.04 origin 色表同款）：
    慢=浅绿→快=深蓝，阈值间线性插值，主分支与退化分支共用

    7 档：≤4MB/s→浅绿(102,255,102)、4-8→黄(255,255,102)、8-16→橙(255,178,102)、
    16-24→红(255,102,102)、24-32→紫(226,140,255)、32-40→蓝(102,204,255)、40MB/s+→深蓝(102,102,255)

    v4.32.0 起报告柱状图改走 `_speed_color` 整格色块方案，本函数保留为兼容接口（勿删）。
    """
    b = sp * 1024 * 1024
    ramp = [
        (0.0, (102, 255, 102)),  # 0        → 浅绿（慢）
        (4 * 1024 * 1024, (102, 255, 102)),  # 4MB/s    → 浅绿
        (8 * 1024 * 1024, (255, 255, 102)),  # 8MB/s    → 黄
        (16 * 1024 * 1024, (255, 178, 102)),  # 16MB/s   → 橙
        (24 * 1024 * 1024, (255, 102, 102)),  # 24MB/s   → 红
        (32 * 1024 * 1024, (226, 140, 255)),  # 32MB/s   → 紫
        (40 * 1024 * 1024, (102, 204, 255)),  # 40MB/s   → 蓝
        (50 * 1024 * 1024, (102, 102, 255)),  # 50MB/s+  → 深蓝（快）
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


def _bar_color_rel(t: float) -> tuple:
    """柱状图配色（行内相对分级，v4.23.0 引入；v4.24.0 起未调用，接口保留）

    与柱高共用同一 min-max 归一化，颜色跟随起伏：矮红=慢、高绿=快；
    7 档色板在 [0,1] 等距插值，红=慢、绿=快，行内起伏一眼可读。
    分档插值结构参考 SSRSpeedN v1.04 origin 色表（与 config.SPEED_COLORS 同源），
    色系按要求由"绿慢蓝快"改为"红慢绿快"
    """
    ramp = [
        (0.0, (178, 34, 34)),  # 0.0   → 深红（行内最慢）
        (1 / 6, (221, 51, 51)),  # 0.167 → 红
        (2 / 6, (221, 102, 51)),  # 0.333 → 橙
        (3 / 6, (221, 187, 0)),  # 0.5   → 黄
        (4 / 6, (154, 180, 34)),  # 0.667 → 黄绿
        (5 / 6, (51, 170, 51)),  # 0.833 → 绿
        (1.0, (0, 128, 0)),  # 1.0   → 深绿（行内最快）
    ]
    if t <= 0:
        return ramp[0][1]
    for i in range(len(ramp) - 1):
        l, cl = ramp[i]
        u, cr = ramp[i + 1]
        if l <= t <= u:
            lev = 0 if u == l else (t - l) / (u - l)
            return tuple(int(a * (1 - lev) + bb * lev) for a, bb in zip(cl, cr))
    return ramp[-1][1]


def _fmt_ms(ms):
    """格式化延迟（v4.36.0：NaN/Inf/负值守卫——此前 NaN 显示 "nanms"、负延迟会被色块误判为快）"""
    if ms is None:
        return "超时"
    try:
        if not math.isfinite(ms) or ms < 0:
            return "--"
    except (TypeError, ValueError):
        return "--"
    return f"{ms:.0f}ms"


def _fmt_mb(s):
    """旧接口保留（v4.32.0 起报告改走 `_fmt_speed`，本函数不再被调用）"""
    return "--" if s is None else f"{s:.1f}MB/s"


# ==================== v4.32.0 新视觉方案取色与格式化 ====================


def _ramp_lerp(keys, v):
    """关键帧线性插值取色"""
    if v <= keys[0][0]:
        return keys[0][1]
    for (a, ca), (b, cb) in zip(keys, keys[1:]):
        if a <= v <= b:
            t = 0 if b == a else (v - a) / (b - a)
            return tuple(int(ca[i] * (1 - t) + cb[i] * t) for i in range(3))
    return keys[-1][1]


def _speed_color(v, report_max):
    """速度取色（MiaoKo 蓝绿冷色系：慢=浅绿 → 中=蓝 → 快=深蓝）
    固定参考上限 MIAO_SPEED_REF=25MB/s：p=log2(1+v)/log2(1+25)，超过 25MB/s 即最蓝。
    高速区平缓（整体色差小），只有极慢才落向浅绿（符合 MiaoKo 参考图）。
    旧接口 report_max 参数保留（不再用于映射，兼容外部调用）。NaN/Inf/负值防御为 0。"""
    if v is None or not math.isfinite(v):
        v = 0
    if v < 0:
        v = 0
    p = math.log2(1 + v) / math.log2(1 + MIAO_SPEED_REF)
    p = max(0.0, min(1.0, p))
    return _ramp_lerp(MIAO_SPEED, p)


def _fmt_speed(v):
    """速度文字：<1MB/s 用 KB/s，<1KB/s 显示 <1KB/s，否则 1 位小数 MB/s"""
    if v is None or not math.isfinite(v):
        return "--"
    if v < 1.0:
        kb = v * 1024
        return "<1KB/s" if kb < 1 else f"{kb:.0f}KB/s"
    return f"{v:.1f}MB/s"


def _resample7(arr):
    """任意长度采样数组线性插值重采样为 7 个点（保持走势形状）"""
    n = len(arr)
    if n == 7:
        return list(arr)
    out = []
    for i in range(7):
        t = i * (n - 1) / 6.0
        lo, hi = int(t), min(int(t) + 1, n - 1)
        frac = t - lo
        out.append(arr[lo] * (1 - frac) + arr[hi] * frac)
    return out


def _resample_n(arr, k):
    """任意长度采样数组线性插值重采样为 k 个点（MiaoKo 每秒柱用，v4.43.0）"""
    n = len(arr)
    if n <= 0:
        return []
    if n == k:
        return list(arr)
    out = []
    for i in range(k):
        t = i * (n - 1) / (k - 1.0) if k > 1 else 0
        lo = int(t)
        hi = min(lo + 1, n - 1)
        frac = t - lo
        out.append(arr[lo] * (1 - frac) + arr[hi] * frac)
    return out


def _stream_block_color(text):
    """流媒体状态归类取色（作用于 _fmt_ss 简化后的状态串）
    归类：待解锁/自制 → pending；解锁/可用 → ok；N/A/查询失败 → na；失败/封锁/连接失败 → fail；
    未知 → unknown；跳过 → skip；未归类（"--"/空/其他）→ None（白底黑字不填色）
    v4.43.0 MiaoKo：补"自制"→pending、"查询失败"→na 归类，色值取柔和色板（config.STREAMING_STATUS_COLORS）"""
    if not text or text == "--":
        return None
    if "待解锁" in text or "自制" in text:
        return STREAMING_STATUS_COLORS["pending"]
    if "解锁" in text or "可用" in text:
        return STREAMING_STATUS_COLORS["ok"]
    if text == "N/A" or "查询失败" in text:
        return STREAMING_STATUS_COLORS["na"]
    if len(text) == 5 and text[0] == "(" and text[-1] == ")" and text[1:4].isdigit():
        # v4.44.0：检测器对未料到的状态码会返回裸 "(503)"——归到"未知"灰，
        # 不再留白（与 miaoko_report.streaming_color 同口径）
        return STREAMING_STATUS_COLORS["unknown"]
    if "失败" in text or "封锁" in text or "连接失败" in text:
        return STREAMING_STATUS_COLORS["fail"]
    if text == "未知":
        return STREAMING_STATUS_COLORS["unknown"]
    if "跳过" in text:
        return STREAMING_STATUS_COLORS["skip"]
    return None


def _ip_type_block(r):
    """IP 类型色块（家宽/移动→绿、商宽/机房→黄、代理/VPN/Tor→红）；无数据 → None"""
    d = r.ip_info
    if d.get("error") or not d.get("ip"):
        return None
    # 核心风控字段（机房/代理/移动）全为 None → 数据源无风控数据
    if (
        d.get("is_datacenter") is None
        and d.get("is_proxy") is None
        and d.get("is_mobile") is None
    ):
        return None
    if d.get("is_tor") or d.get("is_proxy") or d.get("is_vpn"):
        return IP_TYPE_COLORS["proxy"]
    if d.get("is_datacenter"):
        return IP_TYPE_COLORS["datacenter"]
    return IP_TYPE_COLORS["residential"]


def _ip_risk_block(r):
    """IP 风险色块（分档与 _ctxt 文本口径一致：低<20→绿、中<60→黄、高→红）；无数据 → None"""
    d = r.ip_info
    if d.get("error") or not d.get("ip"):
        return None
    sc = d.get("risk_score")
    if sc is None:
        return None
    if sc < 20:
        return STREAMING_STATUS_COLORS["ok"]
    if sc < 60:
        return STREAMING_STATUS_COLORS["pending"]
    return STREAMING_STATUS_COLORS["fail"]


def _reuse_block(r):
    """复用色块（完全→深红、中转→深黄、落地→深青）；无数据 → None"""
    key = {"完全复用": "full", "中转复用": "relay", "落地复用": "landing"}.get(
        r.ip_info.get("reuse")
    )
    return REUSE_COLORS.get(key) if key else None


def _ping_value(r):
    """延迟RTT 取色用数值（UDP/代理可达/超时 → None 走灰块）"""
    if is_udp_node(r.node):
        return None
    p = r.tcp_ping
    return p if p is not None and math.isfinite(p) else None


def _http_value(r):
    p = r.http_latency
    return p if p is not None and math.isfinite(p) else None


def _web_value(r):
    avg = r.webpage.get("avg_ms")
    return avg if avg and avg > 0 and math.isfinite(avg) else None


def _speed_value(r):
    s = r.speed
    return s if s is not None and math.isfinite(s) else None


def _maxspeed_value(r):
    v = r.max_speed if r.max_speed is not None else r.speed
    return v if v is not None and math.isfinite(v) else None


def _fmt_ss(s):
    if not isinstance(s, str):
        return "--"  # 类型守卫：streaming 值异常（None/非字符串）不拖垮报告
    if "错误" in s:
        # 简化错误信息：只保留错误类型，去掉括号内的完整类名
        # 如 错误(ClientConnectorError) → 连接失败
        return "连接失败"
    if len(s) > 25:
        if "解锁" in s or "送中" in s:
            return s[:15]
        if "失败" in s:
            return s[:25]
    return s


def _font(size=13):
    # 回退链覆盖 Windows / Linux（含 Noto CJK）/ macOS
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    except Exception:
        pass
    # 无任何 CJK 字体：报告中文将渲染为方框，明确告警（不要静默）
    logger.warning(
        "未找到中文字体（CJK），PNG 报告中文可能显示为方框；"
        "可安装 Noto Sans CJK 或微软雅黑后重试"
    )
    return ImageFont.load_default()


def _font_bd(size=12):
    """加粗字体（v4.32.0：数值格与页眉标题用，msyhbd 优先；无加粗字体回退常规字体）"""
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return _font(size)


def _ctxt(cid, r):
    if cid == "idx":
        return ""
    if cid == "name":
        # PNG 用国家代码形式（[XX]），避免国旗 emoji 在报告中渲染成方框
        nm = _flag_to_text(r.node.name)
        return nm[:24] + "…" if len(nm) > 24 else nm
    if cid == "type":
        # 类型缩写映射（type[:7] 会把 hysteria2→hysteri、wireguard→wiregua 截断失真）
        return {
            "hysteria2": "hy2",
            "wireguard": "wg",
            "shadowsocks": "ss",
            "hysteria": "hy",
            "anytls": "anytls",
            "socks5": "socks5",
        }.get(r.node.type, r.node.type[:7])
    if cid == "ping":
        if is_udp_node(r.node):
            return "UDP"
        if r.tcp_ping is not None:
            if r.tcp_loss:
                return f"{_fmt_ms(r.tcp_ping)}({r.tcp_loss}丢)"
            return _fmt_ms(r.tcp_ping)
        if r.tcp_probe:
            return "代理可达"
        return "超时"
    if cid == "http":
        if r.http_latency is None:
            return "--"  # 无延迟数据（非超时）
        return _fmt_ms(r.http_latency)
    if cid == "speed":
        if r.speed is not None:
            return _fmt_speed(r.speed)  # v4.32.0：<1MB/s 用 KB/s 显示
        if r.error:
            # v4.28.0：无速度数据时如实显示失败原因（节点不可达/切换失败/下载失败等），
            # 按显示宽度截断防长异常文本撑破列
            return _trunc_width(r.error, 10)
        return "--"
    if cid == "maxspeed":
        return _fmt_speed(r.max_speed if r.max_speed is not None else r.speed)
    if cid == "ip_type":
        d = r.ip_info
        if d.get("error") or not d.get("ip"):
            return "--"
        # v4.19.0：核心风控字段（机房/代理/移动）全为 None → 数据源无风控数据
        if (
            d.get("is_datacenter") is None
            and d.get("is_proxy") is None
            and d.get("is_mobile") is None
        ):
            return "--"
        if d.get("is_tor"):
            return "Tor 出口"
        if d.get("is_proxy") or d.get("is_vpn"):
            return "代理/VPN IP"
        if d.get("is_datacenter"):
            return "商宽/机房 IP"
        if d.get("is_mobile"):
            return "移动网络 IP"
        return "家宽 IP"
    if cid == "ip_risk":
        d = r.ip_info
        if d.get("error") or not d.get("ip"):
            return "--"
        sc = d.get("risk_score")
        if sc is None:
            return "--"  # 数据源无风控字段
        if sc < 20:
            return f"低({sc})"
        if sc < 60:
            return f"中({sc})"
        return f"高({sc})"
    if cid == "asn":
        asn = r.ip_info.get("asn") or ""
        org = r.ip_info.get("org") or ""
        txt = f"{asn} {org}" if asn and org else (asn or org or "--")
        return txt[:35]
    if cid == "reuse":
        return r.ip_info.get("reuse") or "--"
    if cid == "web_avg":
        avg = r.webpage.get("avg_ms")
        return f"{avg:.0f}ms" if avg and avg > 0 else "--"
    if cid == "udp":
        return _udp_type_text(r.node)
    return _fmt_ss(r.streaming.get(cid, ""))


def sort_results(results, sort_by):
    # sort_by = "none"|"default"|"max_desc"|"max_asc"|"avg_desc"|"avg_asc"|"name_asc"|"name_desc"
    # v4.33.0：default 与 none 同义 = 保持订阅原始顺序（默认排序改为订阅顺序）
    if sort_by in ("none", "default"):
        return list(results)  # 保持订阅原始顺序
    if sort_by == "max_desc":
        return sorted(
            results,
            key=lambda r: (
                r.max_speed is None,
                r.speed is None,
                -(r.max_speed or r.speed or 0),
            ),
        )
    if sort_by == "max_asc":
        return sorted(
            results,
            key=lambda r: (
                r.max_speed is None,
                r.speed is None,
                (r.max_speed or r.speed or 0),
            ),
        )
    if sort_by == "avg_desc":
        return sorted(results, key=lambda r: (r.speed is None, -(r.speed or 0)))
    if sort_by == "avg_asc":
        return sorted(results, key=lambda r: (r.speed is None, (r.speed or 0)))
    if sort_by == "name_asc":
        return sorted(results, key=lambda r: r.node.name)
    if sort_by == "name_desc":
        return sorted(results, key=lambda r: r.node.name, reverse=True)
    # v4.36.0：未知排序方式回退订阅顺序并告警（此前静默回退最大速度降序，与默认语义矛盾）
    logger.warning("未知排序方式 %r，回退订阅顺序", sort_by)
    return list(results)


def print_console_summary(results, sort_by="default", top: int = 5) -> None:
    """控制台 TOP N 小结：不开 PNG 也能看结果（按排序取前 N 名）

    显示列：名称 / 延迟 / HTTP / 平均 / 最大 /（有流媒体数据时）解锁 /（有 IP 数据时）风险
    """
    if not results:
        return
    ranked = sort_results(results, sort_by)
    has_stream = any(r.streaming for r in results if r.streaming)
    has_ip = any(r.ip_info for r in results if r.ip_info)
    hdr = (
        f"{_pad_right('节点名称', 30)} {_pad_right('延迟', 7)} {_pad_right('HTTP', 7)} "
        f"{_pad_right('平均', 10)} {_pad_right('最大', 10)}"
    )
    if has_stream:
        hdr += f" {_pad_right('解锁', 5)}"
    if has_ip:
        hdr += f" {_pad_right('风险', 5)}"
    print(hdr)
    print("-" * _str_width(hdr))
    for r in ranked[:top]:
        name = _trunc_width(_flag_to_text(r.node.name), 30)
        if is_udp_node(r.node):
            ping = "UDP"
        elif r.tcp_ping is not None and math.isfinite(r.tcp_ping) and r.tcp_ping >= 0:
            ping = f"{r.tcp_ping:.0f}ms"
        else:
            ping = "--"
        http = (
            f"{r.http_latency:.0f}ms"
            if r.http_latency is not None
            and math.isfinite(r.http_latency)
            and r.http_latency >= 0
            else "--"
        )
        avg = f"{r.speed:.1f}MB/s" if r.speed and math.isfinite(r.speed) else "--"
        mx = (
            f"{r.max_speed:.1f}MB/s"
            if r.max_speed and math.isfinite(r.max_speed)
            else "--"
        )
        line = (
            f"{_pad_right(name, 30)} {_pad_right(ping, 7)} {_pad_right(http, 7)} "
            f"{_pad_right(avg, 10)} {_pad_right(mx, 10)}"
        )
        if has_stream:
            # v4.27.0：类型守卫（streaming 值异常为 None 时小结不再抛 TypeError 静默消失）
            un = sum(
                1
                for v in r.streaming.values()
                if isinstance(v, str) and ("解锁" in v or "可用" in v)
            )
            line += f" {_pad_right(str(un), 5)}"
        if has_ip:
            risk = r.ip_info.get("risk_score")
            line += f" {_pad_right('--' if risk is None else str(risk), 5)}"
        print(line)
    if len(ranked) > top:
        print(f"... 共 {len(ranked)} 个节点，完整结果见报告")


def _new_report_timestamp() -> str:
    """生成本次运行共享的报告时间戳（PNG/JSON 同名配对）

    v4.29.0：秒级 + 同秒冲突加毫秒后缀（与 new_run_log 同策略），
    且 PNG 与 JSON 必须共用同一个值——run 收尾生成一次传入两个导出函数，
    同时修复旧实现各自取秒级时间戳的跨秒配对竞态。
    """
    base = time.strftime("%Y%m%d_%H%M%S")
    try:
        names = os.listdir(OUTPUT_DIR)
    except OSError:
        names = []
    if any(base in n for n in names):
        base += f"_{int(time.monotonic() * 1000) % 1000:03d}"
    return base


def export_results_json(
    results: list[TestResult],
    mode: str,
    display_mode: str | None = None,
    report_ts: str | None = None,
    run_bytes: int | None = None,
) -> str:
    """导出测试结果为 JSON 文件（display_mode 为原始模式名，用于文件名与 mode 字段）

    report_ts 为本次运行共享时间戳（缺省时函数内部生成，兼容直接调用）。
    """
    display_mode = display_mode or mode
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = report_ts or _new_report_timestamp()
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
            "tcp_loss": r.tcp_loss,
            "tcp_probe": r.tcp_probe,
            "sub_index": r.node.sub_index,  # v4.31.0：订阅序号（分组对比用；旧数据无此字段）
            "http_latency_ms": r.http_latency,
            "speed_mbs": r.speed,
            "max_speed_mbs": r.max_speed,
            "speed_per_sec_mbs": r.speed_per_sec,
            "streaming": r.streaming,
            "ip_info": r.ip_info,
            "webpage": r.webpage,
            "error": r.error,
        }
        data.append(entry)

    with open(fpath, "w", encoding="utf-8") as f:
        top = {
            "mode": display_mode,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": VERSION,
            "results": data,
        }
        if run_bytes is not None:
            top["run_bytes"] = int(run_bytes)  # v4.29.0：本次实测下载字节
        json.dump(
            top, f, ensure_ascii=False, indent=2, allow_nan=False
        )  # allow_nan=False：NaN/Infinity 不写出非法 JSON
    return fpath


def generate_report_image(
    results,
    mode,
    total_time,
    sort_by="default",
    display_mode=None,
    report_ts=None,
    run_bytes=None,
):
    """生成 PNG 报告 —— MiaoKo 风格（v4.44 起替换原自绘）

    mode 驱动渲染：speed/basic → 下载速度表(红粉)；normal/full/streaming → 流媒体检测表(蓝绿+状态色)。
    report_ts 为本次运行共享时间戳（缺省时函数内部生成，兼容直接调用）。
    """
    from .miaoko_report import render_miaoko_report

    display_mode = display_mode or mode
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = report_ts or _new_report_timestamp()
    fpath = os.path.join(OUTPUT_DIR, f"测速结果_{display_mode}_{ts}.png")
    if not results:
        img = Image.new("RGB", (800, 200), "white")
        ImageDraw.Draw(img).text(
            (50, 80), "无有效节点可显示", fill="black", font=_font(16)
        )
        try:
            img.save(fpath)
        finally:
            img.close()
        return fpath
    # v4.44.0：排序改由本函数负责（v4.33.0 语义：none/default = 保持订阅顺序）。
    # 此前自绘版本在函数内部排序，改成委托渲染后漏掉了，会出现"选了排序方式但表格仍是订阅顺序"。
    ordered = sort_results(results, sort_by)
    # v4.40.0：画布行数上限，超出的只在页脚提示（完整数据在同名 JSON）
    max_rows = 300
    shown = ordered[:max_rows]
    truncated = (len(shown), len(ordered)) if len(ordered) > max_rows else None
    if truncated:
        logger.warning(
            "节点数 %d 超过画布上限，PNG 仅显示前 %d 个（完整数据见同名 JSON）",
            len(ordered), len(shown),
        )
    render_miaoko_report(
        shown,
        mode,
        total_time,
        sort_by=sort_by,
        display_mode=display_mode,
        run_bytes=run_bytes,
        truncated=truncated,
        output_path=fpath,
    )
    return fpath


__all__ = [
    "_get_speed_color",
    "_bar_color",
    "_bar_color_rel",
    "_fmt_ms",
    "_fmt_mb",
    "_fmt_ss",
    "_font",
    "_font_bd",
    "_ramp_lerp",
    "_speed_color",
    "_fmt_speed",
    "_resample7",
    "_resample_n",
    "_stream_block_color",
    "_ctxt",
    "sort_results",
    "print_console_summary",
    "export_results_json",
    "generate_report_image",
    "_new_report_timestamp",
]
