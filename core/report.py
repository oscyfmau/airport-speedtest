#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告生成：PNG 可视化 / JSON 导出 / 排序 / 格式化"""
import json
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
    if cid=="speed": return _fmt_mb(r.speed)
    if cid=="maxspeed": return _fmt_mb(r.max_speed if r.max_speed is not None else r.speed)
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
            "tcp_loss": r.tcp_loss,
            "tcp_probe": r.tcp_probe,
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
        json.dump({
            "mode": display_mode,
            "export_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": VERSION,
            "results": data,
        }, f, ensure_ascii=False, indent=2, allow_nan=False)  # allow_nan=False：NaN/Infinity 不写出非法 JSON
    return fpath


def generate_report_image(results, mode, total_time, sort_by="default", display_mode=None):
    """生成 PNG 报告：mode 驱动列布局，display_mode 驱动文件名与页眉"""
    display_mode = display_mode or mode
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fpath = os.path.join(OUTPUT_DIR, f"测速结果_{display_mode}_{ts}.png")
    if not results:
        img = Image.new("RGB", (800, 200), "white")
        ImageDraw.Draw(img).text((50, 80), "无有效节点可显示", fill="black", font=_font(16))
        try:
            img.save(fpath)
        finally:
            img.close()
        return fpath

    font,fsm,flg = _font(12),_font(10),_font(13)
    has_ip = any(r.ip_info for r in results if r.ip_info)
    has_sp = any(r.streaming for r in results if r.streaming)
    has_web = any(r.webpage for r in results if r.webpage)
    stream_ids = set()
    if has_sp:
        for r in results: stream_ids.update(r.streaming.keys())
    has_spd = any(r.speed is not None for r in results)
    
    # ---- 列布局（按模式） ----
    if mode in ("speed", "basic"):
        cols = [("idx","#",36,"c"),("name","节点名称",210,"l"),("type","类型",72,"c"),
                ("ping","延迟RTT",84,"c"),("http","HTTP延迟",88,"c"),
                ("speed","平均速度",92,"c"),("maxspeed","最大速度",92,"c"),("speed_bar","每秒速度",80,"c"),
                ("udp","UDP类型",62,"c")]
    elif mode in ("normal","full"):
        cols = [("idx","#",34,"c"),("name","节点名称",180,"l"),("type","类型",68,"c"),
                ("ping","延迟RTT",76,"c"),("http","HTTP延迟",80,"c")]
        if has_web:
            cols.append(("web_avg","网页均耗",84,"c"))
        if has_ip:
            cols += [("ip_type","IP类型",82,"c"),("ip_risk","IP风险",72,"c"),("reuse","复用",64,"c")]
        # 渲染本次实际测过的全部流媒体列（COMMON 8 个或 FULL 33 个）
        name_map = {s["id"]: s["name"] for s in FULL_STREAMING_SERVICES}
        for sid in [s["id"] for s in FULL_STREAMING_SERVICES if s["id"] in stream_ids]:
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
        for sid in [s["id"] for s in FULL_STREAMING_SERVICES if s["id"] in stream_ids]:
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
    mn = {"speed":"简单测速","basic":"简单测速","normal":"标准测试","full":"完整测速",
          "streaming":"流媒体","streaming_ai":"AI流媒体","streaming_all":"全部流媒体"}
    hdr = f"speed_test.py v{VERSION} | {mn.get(display_mode, display_mode)}"
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
                    row_mx = max(speeds)
                    row_min = min(speeds)
                    span = row_mx - row_min
                    bar_w = max(4, (w - 6) // n - 1)
                    bars = []
                    for i, sp in enumerate(speeds):
                        # v4.24.0：柱高 = 行内 min-max（只管起伏形状，每行必有起伏），
                        # 颜色 = 绝对速度（表达真实快慢，红=慢绿=快，高柱子也可以配慢色）
                        if span > 0:
                            ratio = (sp - row_min) / span
                            bh = 3 + int((rh - 6 - 3) * ratio)   # 3px → 20px
                        else:
                            bh = rh - 6                            # 行内全相等（边缘情况）：满高
                        bx = x + 3 + int(i * (bar_w + 1))
                        bars.append((bx, bar_w, bh, sp))
                    # 第一遍：先把柱子立起来（浅灰底）
                    for bx, bw, bh, _ in bars:
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bw, y+rh-4)], fill=(200, 200, 200))
                    # 第二遍：按绝对速度上色（红=慢、绿=快，7 档分级，跨行可比）
                    for bx, bw, bh, sp in bars:
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bw, y+rh-4)], fill=_bar_color(sp))
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bw, y+rh-4)], outline="#666", width=1)
                elif r.speed is not None:
                    # 退化分支（v4.24.0）：无每秒数组，画 8 根等高矮柱（12px），
                    # 颜色用绝对速度（_bar_color）——视觉上与其他行统一为多根柱子，
                    # 并以矮柱区分"无每秒数据"的节点
                    n = 8
                    bar_w = max(4, (w - 6) // n - 1)
                    col = _bar_color(r.speed)
                    bh = 12
                    for i in range(n):
                        bx = x + 3 + int(i * (bar_w + 1))
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bar_w, y+rh-4)], fill=(200, 200, 200))
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bar_w, y+rh-4)], fill=col)
                        dr.rectangle([(bx, y+rh-4-bh), (bx+bar_w, y+rh-4)], outline="#666", width=1)
            elif cid=="ip_risk":
                sc2 = r.ip_info.get("risk_score")
                if sc2 is None:
                    fc = "#999999"  # 无风控数据（--）灰色，不按 0 分染绿
                else:
                    fc = "#22AA22" if sc2<30 else "#DDBB00" if sc2<60 else "#DD3333"
            elif cid=="ip_type":
                di = r.ip_info
                # v4.19.0：Tor/代理/VPN 红、机房橙、家宽/移动绿
                if di.get("is_tor") or di.get("is_proxy") or di.get("is_vpn"):
                    fc = "#DD3333"
                elif di.get("is_datacenter"):
                    fc = "#DD8833"
                else:
                    fc = "#33AA55"
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
    # 本地时区名（不用硬编码 CST：非中国时区用户标注才正确）
    tz_name = time.strftime("%Z") or "本地时间"
    ftr3 = (f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name})"
            f" | Powered by speed_test.py v{VERSION}")
    if len(results) > max_rows:
        ftr3 += f" | 仅显示前 {max_rows}/{len(results)} 节点"
    dr.text((pad, y), ftr1, fill=dg, font=fsm)
    dr.text((pad, y+14), ftr2, fill=dg, font=fsm)
    dr.text((pad, y+28), ftr3, fill=dg, font=fsm)
    # 调整页脚高度
    dr.rectangle([(pad,0),(tw-pad,th-1)], outline="#CCC", width=1)
    try:
        img.save(fpath)
    finally:
        img.close()
    return fpath

__all__ = ['_get_speed_color', '_bar_color', '_bar_color_rel', '_fmt_ms', '_fmt_mb', '_fmt_ss', '_font', '_ctxt', 'sort_results', 'print_console_summary', 'export_results_json', 'generate_report_image']
