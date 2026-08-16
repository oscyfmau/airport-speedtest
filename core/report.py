#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告生成：PNG 可视化 / JSON 导出 / 排序 / 格式化"""
import json
import math
import os
import time
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from . import state
from .config import *
from .logging_setup import *
from .models import *
from .utils import *

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
    """柱状图配色（绝对速度分档，v4.25.0 起 = SSRSpeedN v1.04 origin 色表同款）：
    慢=浅绿→快=深蓝，阈值间线性插值，主分支与退化分支共用

    7 档：≤4MB/s→浅绿(102,255,102)、4-8→黄(255,255,102)、8-16→橙(255,178,102)、
    16-24→红(255,102,102)、24-32→紫(226,140,255)、32-40→蓝(102,204,255)、40MB/s+→深蓝(102,102,255)
    """
    b = sp * 1024 * 1024
    ramp = [
        (0.0, (102, 255, 102)),                   # 0        → 浅绿（慢）
        (4 * 1024 * 1024, (102, 255, 102)),       # 4MB/s    → 浅绿
        (8 * 1024 * 1024, (255, 255, 102)),       # 8MB/s    → 黄
        (16 * 1024 * 1024, (255, 178, 102)),      # 16MB/s   → 橙
        (24 * 1024 * 1024, (255, 102, 102)),      # 24MB/s   → 红
        (32 * 1024 * 1024, (226, 140, 255)),      # 32MB/s   → 紫
        (40 * 1024 * 1024, (102, 204, 255)),      # 40MB/s   → 蓝
        (50 * 1024 * 1024, (102, 102, 255)),      # 50MB/s+  → 深蓝（快）
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
        (0.0, (178, 34, 34)),      # 0.0   → 深红（行内最慢）
        (1 / 6, (221, 51, 51)),    # 0.167 → 红
        (2 / 6, (221, 102, 51)),   # 0.333 → 橙
        (3 / 6, (221, 187, 0)),    # 0.5   → 黄
        (4 / 6, (154, 180, 34)),   # 0.667 → 黄绿
        (5 / 6, (51, 170, 51)),    # 0.833 → 绿
        (1.0, (0, 128, 0)),        # 1.0   → 深绿（行内最快）
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
    return "超时" if ms is None else f"{ms:.0f}ms"


def _fmt_mb(s):
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
    """速度取色（分场景自适应，高低速可同图）
    1) 全表低速度（report_max < SPEED_ADAPT_MAX=8MB/s）：线性铺满 0..report_max（红→绿全用上）；
    2) 混合/常规场景（report_max >= 8MB/s）：对数映射 p=log2(1+v)/log2(1+report_max)
       ——低端拉伸（0.1/1/5MB/s 各自拉开色差）、高端压缩（突刺不把慢节点挤成一片红），
       最慢=深红、最快=深绿。
    NaN/Inf 防御为 0。"""
    if v is None or not math.isfinite(v):
        v = 0
    if report_max < SPEED_ADAPT_MAX:
        scale = report_max / 50.0
        return _ramp_lerp([(t * scale, c) for t, c in SPEED_RAMP_R2G], v)
    p = math.log2(1 + v) / math.log2(1 + report_max)
    return _ramp_lerp(SPEED_NORM, p)


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


def _stream_block_color(text):
    """流媒体状态归类取色（作用于 _fmt_ss 简化后的状态串）
    归类：待解锁 → pending；解锁/可用 → ok；N/A → na；失败/封锁/连接失败 → fail；
    未知 → unknown；跳过 → skip；未归类（"--"/空/其他）→ None（斑马底黑字不填色）"""
    if not text or text == "--":
        return None
    if "待解锁" in text:
        return STREAMING_STATUS_COLORS["pending"]
    if "解锁" in text or "可用" in text:
        return STREAMING_STATUS_COLORS["ok"]
    if text == "N/A":
        return STREAMING_STATUS_COLORS["na"]
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
    if (d.get("is_datacenter") is None and d.get("is_proxy") is None
            and d.get("is_mobile") is None):
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
        r.ip_info.get("reuse"))
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
        if "解锁" in s or "送中" in s: return s[:15]
        if "失败" in s: return s[:25]
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
    logger.warning("未找到中文字体（CJK），PNG 报告中文可能显示为方框；"
                   "可安装 Noto Sans CJK 或微软雅黑后重试")
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
    if cid=="idx": return ""
    if cid=="name":
        # PNG 用国家代码形式（[XX]），避免国旗 emoji 在报告中渲染成方框
        nm = _flag_to_text(r.node.name)
        return nm[:24] + "…" if len(nm) > 24 else nm
    if cid=="type":
        # 类型缩写映射（type[:7] 会把 hysteria2→hysteri、wireguard→wiregua 截断失真）
        return {"hysteria2": "hy2", "wireguard": "wg", "shadowsocks": "ss",
                "hysteria": "hy", "anytls": "anytls", "socks5": "socks5"}.get(
            r.node.type, r.node.type[:7])
    if cid=="ping":
        if is_udp_node(r.node): return "UDP"
        if r.tcp_ping is not None:
            if r.tcp_loss:
                return f"{_fmt_ms(r.tcp_ping)}({r.tcp_loss}丢)"
            return _fmt_ms(r.tcp_ping)
        if r.tcp_probe: return "代理可达"
        return "超时"
    if cid=="http":
        if r.http_latency is None: return "--"  # 无延迟数据（非超时）
        return _fmt_ms(r.http_latency)
    if cid=="speed":
        if r.speed is not None:
            return _fmt_speed(r.speed)  # v4.32.0：<1MB/s 用 KB/s 显示
        if r.error:
            # v4.28.0：无速度数据时如实显示失败原因（节点不可达/切换失败/下载失败等），
            # 按显示宽度截断防长异常文本撑破列
            return _trunc_width(r.error, 10)
        return "--"
    if cid=="maxspeed":
        return _fmt_speed(r.max_speed if r.max_speed is not None else r.speed)
    if cid=="ip_type":
        d=r.ip_info
        if d.get("error") or not d.get("ip"): return "--"
        # v4.19.0：核心风控字段（机房/代理/移动）全为 None → 数据源无风控数据
        if (d.get("is_datacenter") is None and d.get("is_proxy") is None
                and d.get("is_mobile") is None): return "--"
        if d.get("is_tor"): return "Tor 出口"
        if d.get("is_proxy") or d.get("is_vpn"): return "代理/VPN IP"
        if d.get("is_datacenter"): return "商宽/机房 IP"
        if d.get("is_mobile"): return "移动网络 IP"
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
    if cid=="reuse": return r.ip_info.get("reuse") or "--"
    if cid=="web_avg":
        avg = r.webpage.get("avg_ms")
        return f"{avg:.0f}ms" if avg and avg > 0 else "--"
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


def print_console_summary(results, sort_by="default", top: int = 5) -> None:
    """控制台 TOP N 小结：不开 PNG 也能看结果（按排序取前 N 名）

    显示列：名称 / 延迟 / HTTP / 平均 / 最大 /（有流媒体数据时）解锁 /（有 IP 数据时）风险
    """
    if not results:
        return
    ranked = sort_results(results, sort_by)
    has_stream = any(r.streaming for r in results if r.streaming)
    has_ip = any(r.ip_info for r in results if r.ip_info)
    hdr = (f"{_pad_right('节点名称', 30)} {_pad_right('延迟', 7)} {_pad_right('HTTP', 7)} "
           f"{_pad_right('平均', 10)} {_pad_right('最大', 10)}")
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
        elif r.tcp_ping is not None:
            ping = f"{r.tcp_ping:.0f}ms"
        else:
            ping = "--"
        http = f"{r.http_latency:.0f}ms" if r.http_latency is not None else "--"
        avg = f"{r.speed:.1f}MB/s" if r.speed else "--"
        mx = f"{r.max_speed:.1f}MB/s" if r.max_speed else "--"
        line = (f"{_pad_right(name, 30)} {_pad_right(ping, 7)} {_pad_right(http, 7)} "
                f"{_pad_right(avg, 10)} {_pad_right(mx, 10)}")
        if has_stream:
            # v4.27.0：类型守卫（streaming 值异常为 None 时小结不再抛 TypeError 静默消失）
            un = sum(1 for v in r.streaming.values()
                     if isinstance(v, str) and ("解锁" in v or "可用" in v))
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


def export_results_json(results: list[TestResult], mode: str, display_mode: str = None,
                        report_ts: str = None, run_bytes: int = None) -> str:
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
        json.dump(top, f, ensure_ascii=False, indent=2, allow_nan=False)  # allow_nan=False：NaN/Infinity 不写出非法 JSON
    return fpath


def generate_report_image(results, mode, total_time, sort_by="default", display_mode=None,
                          report_ts: str = None, run_bytes: int = None):
    """生成 PNG 报告：mode 驱动列布局，display_mode 驱动文件名与页眉

    v4.32.0 视觉改版：整格色块 + 白网格线 + 纯黑直绘文字 + 每秒恒 7 柱；
    版式参数与取色规则见《报告图片设计方案》（REPORT_* / LATENCY_RAMP / SPEED_* 常量）。
    report_ts 为本次运行共享时间戳（缺省时函数内部生成，兼容直接调用）。
    """
    display_mode = display_mode or mode
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = report_ts or _new_report_timestamp()
    fpath = os.path.join(OUTPUT_DIR, f"测速结果_{display_mode}_{ts}.png")
    if not results:
        img = Image.new("RGB", (800, 200), "white")
        ImageDraw.Draw(img).text((50, 80), "无有效节点可显示", fill="black", font=_font(16))
        try:
            img.save(fpath)
        finally:
            img.close()
        return fpath

    font = _font(12)       # 常规 12px：表头/名称/类型/流媒体/状态格
    fsm = _font(10)        # 页眉行2 / 序号 / 页脚行
    fsm2 = _font(9)        # 页脚行3 右侧品牌行
    fbd = _font_bd(12)     # 数值格 12px 加粗
    flg = _font_bd(14)     # 页眉标题 14px 加粗
    has_ip = any(r.ip_info for r in results if r.ip_info)
    has_sp = any(r.streaming for r in results if r.streaming)
    has_web = any(r.webpage for r in results if r.webpage)
    stream_ids = set()
    if has_sp:
        for r in results: stream_ids.update(r.streaming.keys())
    has_spd = any(r.speed is not None for r in results)

    # ---- 列布局（列序与 v4.31.0 一致，仅调整宽度与渲染） ----
    name_map = {s["id"]: s["name"] for s in FULL_STREAMING_SERVICES}
    if mode in ("speed", "basic"):
        cols = [("idx","#",32,"c"),("name","节点名称",210,"l"),("type","类型",72,"c"),
                ("ping","延迟RTT",84,"c"),("http","HTTP延迟",88,"c"),
                ("speed","平均速度",92,"c"),("maxspeed","最高速度",92,"c"),("speed_bar","每秒速度",100,"c"),
                ("udp","UDP类型",62,"c")]
    elif mode in ("normal","full"):
        cols = [("idx","#",30,"c"),("name","节点名称",180,"l"),("type","类型",68,"c"),
                ("ping","延迟RTT",76,"c"),("http","HTTP延迟",80,"c")]
        if has_web:
            cols.append(("web_avg","网页均耗",84,"c"))
        if has_ip:
            cols += [("ip_type","IP类型",82,"c"),("ip_risk","IP风险",72,"c"),("reuse","复用",64,"c")]
        # 渲染本次实际测过的全部流媒体列（COMMON 8 个或 FULL 33 个）
        for sid in [s["id"] for s in FULL_STREAMING_SERVICES if s["id"] in stream_ids]:
            cols.append((sid, name_map.get(sid, sid), 64, "c"))
        if has_spd:
            cols += [("speed","平均速度",82,"c"),("maxspeed","最高速度",82,"c"),("speed_bar","每秒速度",76,"c")]
        if has_ip:
            cols.append(("asn","ASN",130,"l"))
        cols.append(("udp","UDP类型",58,"c"))
    elif mode == "streaming":
        # 纯流媒体模式：简洁，不显示测速相关列
        cols = [("idx","#",30,"c"),("name","节点名称",180,"l"),("type","类型",68,"c")]
        for sid in [s["id"] for s in FULL_STREAMING_SERVICES if s["id"] in stream_ids]:
            cols.append((sid, name_map.get(sid, sid), 64, "c"))
    elif mode == "quick":
        # v4.30.0 快速检测：4 核心流媒体 + 近似速度（不画每秒柱——并行数据画柱易误导）
        cols = [("idx","#",32,"c"),("name","节点名称",180,"l"),("type","类型",68,"c"),
                ("ping","延迟RTT",76,"c"),("http","HTTP延迟",80,"c")]
        for sid in [s["id"] for s in FULL_STREAMING_SERVICES if s["id"] in stream_ids]:
            cols.append((sid, name_map.get(sid, sid), 64, "c"))
        if has_spd:
            cols += [("speed","平均速度",82,"c"),("maxspeed","最高速度",82,"c")]
        cols.append(("udp","UDP类型",58,"c"))
    else:
        cols = [("idx","#",30,"c"),("name","节点名称",180,"l")]

    # ---- 计算列宽 ----
    # 数值列（延迟/速度）自适应列宽 = max(默认宽, 最长文本(msyhbd 12px)宽 + 14)，数字永不被截断；
    # 其余列沿用现有自动估宽逻辑（内容自适应 + 截断加省略号）
    numeric_cids = {"ping", "http", "web_avg", "speed", "maxspeed"}
    cw = {}
    for cid, title, dw, _ in cols:
        w = dw
        for r in results:  # 遍历全部行估算列宽（画布上限 300 行）
            txt = _ctxt(cid, r)
            f = fbd if cid in numeric_cids else font
            extra = 14 if cid in numeric_cids else 18
            try:
                tw = int(f.getlength(txt) + extra)
            except Exception:
                tw = int(max(dw - 10, len(txt) * 7 + 10))
            w = max(w, tw)
        cw[cid] = int(w)

    # ---- 版式骨架（v4.32.0） ----
    pad, hh, hdr_h, fh, gap = 14, 40, 30, 54, 2
    rh = 36 if mode in ("speed", "basic", "quick") else 30  # 数据行高按模式
    iw = sum(cw.values())
    tw = int(iw + pad * 2)
    # 最多显示 300 个节点，防止图片内存溢出
    max_rows = 300
    nh = min(len(results), max_rows)
    th = int(hh + hdr_h + nh * rh + gap + fh)

    img = Image.new("RGB", (tw, th), REPORT_PAGE_BG)
    dr = ImageDraw.Draw(img)

    # ---- 页眉（40px）：行1 标题居中加粗，行2 左右分布，y=38 白分隔线 ----
    mn = {"speed":"简单测速","basic":"简单测速","normal":"标准测试","full":"完整测速",
          "streaming":"流媒体","streaming_ai":"AI流媒体","streaming_all":"全部流媒体",
          "quick":"快速检测"}
    hdr = f"speed_test.py v{VERSION} | {mn.get(display_mode, display_mode)}"
    dr.text((tw / 2, 9), hdr, font=flg, fill=REPORT_BLACK, anchor="ma")
    dr.text((pad, 27), f"订阅: {len(results)} 节点 | 测试耗时: {total_time:.0f}s",
            font=fsm, fill=REPORT_BLACK, anchor="lm")
    sort_names = {"none":"订阅顺序","default":"最大速度降序","max_desc":"最大速度降序","max_asc":"最大速度升序",
                  "avg_desc":"平均速度降序","avg_asc":"平均速度升序",
                  "name_asc":"名称A→Z","name_desc":"名称Z→A"}
    dr.text((tw - pad, 27), f"排序: {sort_names.get(sort_by, sort_by)}",
            font=fsm, fill=REPORT_BLACK, anchor="rm")
    dr.line([(pad, 38), (tw - pad, 38)], fill=REPORT_GRID, width=1)

    # ---- 表头行（30px，REPORT_HEADER_BG，列名 12px 纯黑居中） ----
    y = hh
    dr.rectangle([(pad, y), (tw - pad, y + hdr_h)], fill=REPORT_HEADER_BG)
    x = pad
    for cid, ttl, _, _al in cols:
        dr.text((x + cw[cid] / 2, y + hdr_h / 2), ttl, font=font, fill=REPORT_BLACK, anchor="mm")
        x += cw[cid]
    y += hdr_h

    # ---- report_max（渲染前计算一次，全表共用） ----
    report_max = 0.0
    for r in results:
        v = r.max_speed if r.max_speed is not None else r.speed
        if v is not None and math.isfinite(v):
            report_max = max(report_max, v)

    # ---- 数据行：先画全部内容（色块+文字+柱），网格线最后画 ----
    sr = sort_results(results, sort_by)

    def _cell(dr_, x_, y_, w_, h_, bg_):
        dr_.rectangle([(x_, y_), (x_ + w_ - 1, y_ + h_ - 1)], fill=bg_)

    for idx, r in enumerate(sr[:nh]):  # 只画画布内的行，页脚才不会被顶出画布
        x = pad
        zebra = REPORT_ZEBRA[idx % 2]
        for cid, _, _, al in cols:
            w = cw[cid]
            txt = _ctxt(cid, r)
            if cid == "idx":
                _cell(dr, x, y, w, rh, zebra)
                dr.text((x + w / 2, y + rh / 2), str(idx + 1), font=fsm,
                        fill=REPORT_BLACK, anchor="mm")
            elif cid == "name":
                _cell(dr, x, y, w, rh, zebra)
                dr.text((x + 8, y + rh / 2), txt, font=font, fill=REPORT_BLACK, anchor="lm")
            elif cid in ("type", "udp"):
                _cell(dr, x, y, w, rh, zebra)
                dr.text((x + w / 2, y + rh / 2), txt, font=font, fill=REPORT_BLACK, anchor="mm")
            elif cid == "asn":
                _cell(dr, x, y, w, rh, zebra)
                dr.text((x + 8, y + rh / 2), txt, font=font, fill=REPORT_BLACK, anchor="lm")
            elif cid in ("ping", "http", "web_avg"):
                # 延迟系整格色块：快绿慢红；超时/--/UDP/代理可达 → 灰块
                if cid == "ping":
                    v = _ping_value(r)
                elif cid == "http":
                    v = _http_value(r)
                else:
                    v = _web_value(r)
                bg = _ramp_lerp(LATENCY_RAMP, v) if v is not None else REPORT_SPECIAL_BG
                _cell(dr, x, y, w, rh, bg)
                dr.text((x + w / 2, y + rh / 2), txt, font=fbd, fill=REPORT_BLACK, anchor="mm")
            elif cid in ("speed", "maxspeed"):
                # 速度整格色块：慢红快绿（全表自适应）；无速度 → 斑马底黑字（失败原因）
                v = _speed_value(r) if cid == "speed" else _maxspeed_value(r)
                bg = _speed_color(v, report_max) if v is not None else zebra
                _cell(dr, x, y, w, rh, bg)
                dr.text((x + w / 2, y + rh / 2), txt, font=fbd, fill=REPORT_BLACK, anchor="mm")
            elif cid == "speed_bar":
                # 每秒速度柱：恒 7 根，直接落在斑马底上（无灰色背景）；柱高=行内起伏、柱色=绝对速度
                _cell(dr, x, y, w, rh, zebra)
                speeds = [s for s in (r.speed_per_sec or [])
                          if isinstance(s, (int, float)) and math.isfinite(s)]
                if speeds:
                    speeds = _resample7(speeds)
                    row_mx, row_mn = max(speeds), min(speeds)
                    span = row_mx - row_mn
                    n = 7
                    bw = max(1, (w - 5 - n) // n)  # 7 柱 + 1px 白缝恒不溢出列宽
                    for i, sp in enumerate(speeds):
                        ratio = (sp - row_mn) / span if span > 0 else 1.0
                        bh = 3 + int((rh - 6 - 3) * ratio)   # 3px ~ rh-6px（只表行内起伏形状）
                        bx = x + 3 + i * (bw + 1)
                        # 右边界必须 bx+bw-1：PIL rectangle 右下角为闭区间，写 bx+bw 会盖掉 1px 白缝
                        dr.rectangle([(bx, y + rh - 3 - bh), (bx + bw - 1, y + rh - 3)],
                                     fill=_speed_color(sp, report_max))
                elif _speed_value(r) is not None:
                    # 退化分支：无每秒数组，画 7 根等高 12px 矮柱，颜色统一 = 平均速度
                    bw = max(1, (w - 5 - 7) // 7)
                    col = _speed_color(r.speed, report_max)
                    bh = 12
                    for i in range(7):
                        bx = x + 3 + i * (bw + 1)
                        dr.rectangle([(bx, y + rh - 3 - bh), (bx + bw - 1, y + rh - 3)], fill=col)
            elif cid in ("ip_type", "ip_risk", "reuse"):
                # 状态色块：IP类型 / IP风险 / 复用；无数据 → 斑马底黑字
                if cid == "ip_type":
                    bg = _ip_type_block(r)
                elif cid == "ip_risk":
                    bg = _ip_risk_block(r)
                else:
                    bg = _reuse_block(r)
                _cell(dr, x, y, w, rh, bg or zebra)
                dr.text((x + w / 2, y + rh / 2), txt, font=font, fill=REPORT_BLACK, anchor="mm")
            else:
                # 流媒体列（txt 已经 _fmt_ss 简化）：按状态归类填色，未归类 → 斑马底黑字
                bg = _stream_block_color(txt)
                _cell(dr, x, y, w, rh, bg or zebra)
                dr.text((x + w / 2, y + rh / 2), txt, font=font, fill=REPORT_BLACK, anchor="mm")
            x += w
        y += rh

    # ---- 网格线（先内容、后画线：顺序不可反，否则横线会被下一行填充覆盖） ----
    table_bottom = hh + hdr_h + nh * rh - 1
    bx = pad
    for cid, _, _, _ in cols[:-1]:
        bx += cw[cid]
        dr.line([(bx - 1, hh), (bx - 1, table_bottom)], fill=REPORT_GRID, width=1)
    for k in range(nh + 1):
        hy = hh + hdr_h + k * rh - 1
        dr.line([(pad, hy), (tw - pad, hy)], fill=REPORT_GRID, width=1)

    # ---- 页脚（54px，3 行等距，距数据区 2px） ----
    y += gap
    dr.rectangle([(pad, y), (tw - pad, y + fh)], fill=REPORT_FOOTER_BG)
    ftr1 = ("快速模式（并行近似测速）" if mode == "quick"
            else "TCP RTT 为单次数据交换延迟，HTTP Ping 为单次请求体感延迟。")
    dr.text((pad + 6, y + 6), ftr1, font=fsm, fill=REPORT_BLACK, anchor="lm")
    tcp_ok = [r for r in results if r.tcp_ping is not None]
    succ = sum(1 for r in results if r.tcp_ping is not None or r.tcp_probe)
    avgp = sum(r.tcp_ping for r in tcp_ok) / len(tcp_ok) if tcp_ok else 0
    ftr2 = f"节点: {succ}/{len(results)} 可达 | 平均延迟: {avgp:.0f}ms"
    udp_n = sum(1 for r in results if is_udp_node(r.node))
    if udp_n:
        ftr2 += f" | UDP节点: {udp_n} 个(经HTTP实测)"
    dr.text((pad + 6, y + 20), ftr2, font=fsm, fill=REPORT_BLACK, anchor="lm")
    # 本地时区名（不用硬编码 CST：非中国时区用户标注才正确）
    tz_name = time.strftime("%Z") or "本地时间"
    ftr3 = f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name})"
    if run_bytes is not None and mode != "streaming":
        ftr3 += f" | 本次实测下载 {_fmt_size(run_bytes)}"  # v4.29.0：页脚流量显示
    if len(results) > max_rows:
        ftr3 += f" | 仅显示前 {max_rows}/{len(results)} 节点"
    dr.text((pad + 6, y + 34), ftr3, font=fsm, fill=REPORT_BLACK, anchor="lm")
    dr.text((tw - pad - 6, y + 34), f"Powered by speed_test.py v{VERSION}",
            font=fsm2, fill=REPORT_BLACK, anchor="rm")
    # 外框 REPORT_OUTER（最后画）
    dr.rectangle([(0, 0), (tw - 1, th - 1)], outline=REPORT_OUTER, width=1)
    try:
        img.save(fpath)
    finally:
        img.close()
    return fpath

__all__ = ['_get_speed_color', '_bar_color', '_bar_color_rel', '_fmt_ms', '_fmt_mb', '_fmt_ss', '_font',
           '_font_bd', '_ramp_lerp', '_speed_color', '_fmt_speed', '_resample7', '_stream_block_color',
           '_ctxt', 'sort_results', 'print_console_summary', 'export_results_json',
           'generate_report_image', '_new_report_timestamp']
