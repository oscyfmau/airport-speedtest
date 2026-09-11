#!/usr/bin/env python3
"""MiaoKo 风格报告渲染器（豆包一比一还原版）

把 MiaoKo 的两类报告表格复刻进本工具：
  - 下载速度表：红粉配色（HTTPS延迟 绿→橙红 / 速度 红粉 / 每秒速度柱 红粉）
  - 流媒体检测表：蓝绿+状态色（TLS RTT 绿→红 / HTTPS延迟 绿→橙红 / 速度 蓝绿 /
    流媒体状态色 / IP类型风险 ASN UDP）

本模块只负责「拿数据画图」，并把工具的 TestResult 适配成 MiaoKo 行列结构。
不依赖 report.py，避免循环导入。
"""

import math
import os
import random
import re
import time

from PIL import Image, ImageDraw, ImageFont

from .config import *
from .models import _udp_type_text, is_udp_node
from .utils import _flag_to_text, _trunc_width

# ─────────────────────── 字体（跨平台候选） ───────────────────────


def load_font(size, bold=False):
    if bold:
        candidates = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/PingFang.ttc",
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
        return ImageFont.load_default()


# ─────────────────────── 颜色映射（MiaoKo 精确取色） ───────────────────────


def https_latency_color(ms):
    """HTTP(S) 延迟列背景色（下载表 / 流媒体表共用）：绿→黄绿→黄→橙→橙红"""
    if ms is None or ms <= 0:
        return (200, 200, 200)
    stops = [
        (200, (70, 200, 80)),  # 亮绿
        (400, (130, 210, 65)),  # 黄绿
        (650, (190, 210, 55)),  # 黄
        (900, (220, 180, 45)),  # 浅橙
        (1200, (235, 130, 35)),  # 橙
        (1600, (240, 80, 25)),  # 橙红
        (9999, (220, 45, 15)),  # 红
    ]
    for t, c in stops:
        if ms <= t:
            return c
    return stops[-1][1]


def tls_rtt_color(ms):
    """TLS RTT 列背景色（流媒体表）：绿→黄绿→黄→橙→橙红→红"""
    if ms is None or ms <= 0:
        return (200, 200, 200)
    stops = [
        (80, (60, 230, 60)),  # 亮绿
        (120, (160, 240, 50)),  # 黄绿
        (180, (240, 240, 50)),  # 黄
        (250, (245, 200, 45)),  # 浅橙
        (350, (245, 140, 35)),  # 橙
        (500, (240, 80, 25)),  # 橙红
        (9999, (220, 40, 15)),  # 红
    ]
    for t, c in stops:
        if ms <= t:
            return c
    return stops[-1][1]


def speed_color_red(speed_str):
    """速度列背景色（下载表红粉方案，逐格取色校准）"""
    mb = parse_speed(speed_str)
    if mb is None:
        return (200, 200, 200)
    if mb <= 0:
        return (255, 255, 255)
    stops = [
        (1.0, (187, 216, 217)),  # KB级 — 浅青
        (5.0, (205, 228, 249)),  # 1-5MB — 浅蓝
        (10.0, (175, 200, 230)),  # 5-10MB — 浅蓝紫
        (15.0, (180, 190, 250)),  # 10-15MB — 浅紫蓝
        (22.0, (192, 155, 237)),  # 15-22MB — 紫色
        (32.0, (232, 120, 160)),  # 22-32MB — 粉红
        (45.0, (240, 65, 108)),  # 32-45MB — 品红
        (65.0, (238, 45, 120)),  # 45-65MB — 深品红
        (9999, (245, 35, 118)),  # >65MB — 最深品红
    ]
    for threshold, color in stops:
        if mb <= threshold:
            return color
    return stops[-1][1]


def speed_color_blue(speed_str):
    """速度列背景色（流媒体表蓝绿方案）"""
    mb = parse_speed(speed_str)
    if mb is None:
        return (200, 200, 200)
    if mb <= 0:
        return (180, 180, 180)
    stops = [
        (1, (200, 235, 250)),  # 浅青
        (5, (170, 225, 250)),  # 浅蓝
        (10, (130, 215, 250)),  # 蓝
        (20, (80, 200, 250)),  # 亮蓝
        (40, (50, 180, 245)),  # 蓝
        (70, (40, 160, 240)),  # 深蓝
        (9999, (30, 140, 230)),  # 最深蓝
    ]
    for t, c in stops:
        if mb <= t:
            return c
    return stops[-1][1]


def streaming_color(status):
    """流媒体解锁状态背景色（扩充处理本工具的状态文本，匹配 MiaoKo 配色）"""
    if not status or status == "--":
        return (255, 255, 255)
    s = status.strip()
    if s == "N/A" or "查询失败" in s:
        return (188, 188, 188)
    if len(s) == 5 and s[0] == "(" and s[-1] == ")" and s[1:4].isdigit():
        # v4.44.0：检测器对未料到的状态码会返回裸 "(503)"（真数据里 PrimeVideo 出现过）——
        # 归到"未知"灰，至少看得出"测过但没归类"，不再是白底像没测
        return (178, 218, 255)
    if "失败" in s or "封锁" in s or "连接失败" in s or "错误" in s:
        return (250, 122, 122)
    if "待解锁" in s or "送中" in s or "仅自制剧" in s:
        return (255, 236, 140)
    if s == "未知":
        # v4.19.0 口径：只有完全等于"未知"才算未知状态。
        # streaming.py 会产出"解锁(未知)"（已解锁但拿不到地区码），必须走到下面的解锁色，
        # 用子串判断会把它误判成未知（蓝）
        return (178, 218, 255)
    if "解锁" in s or "可用" in s or "自制" in s:
        return (192, 242, 140)
    if "跳过" in s:
        return (200, 200, 200)
    return (255, 255, 255)


def _streaming_block(status):
    """流媒体单元格底色；空 / 未测 / `--` 返回 None（不填色，保留行底色）

    v4.44.0：旧写法对空值返回纯白 (255,255,255)，而行底色是 #FCFCFC/#F8F8F8，
    于是“未实测”的格子成了纯白亮块，看起来像图被截断。
    """
    if not status or status == "--":
        return None
    return streaming_color(status)


def sparkline_color_red(mb, brightness=1.0):
    """每秒速度柱颜色（下载表红粉）"""
    if mb is None or mb <= 0:
        return (235, 235, 235)
    if mb < 15:
        base = (225, 130, 175)
    elif mb < 30:
        base = (240, 80, 120)
    elif mb < 55:
        base = (250, 50, 115)
    else:
        base = (255, 35, 120)
    r, g, b = base
    factor = 0.75 + brightness * 0.4
    return (
        min(255, int(r * factor)),
        min(255, int(g * factor)),
        min(255, int(b * factor)),
    )


def sparkline_color_blue(mb, brightness=1.0):
    """每秒速度柱颜色（流媒体表蓝绿）"""
    if mb is None or mb <= 0:
        return (220, 220, 220)
    if mb < 10:
        base = (150, 220, 245)
    elif mb < 30:
        base = (80, 195, 245)
    elif mb < 60:
        base = (50, 175, 240)
    else:
        base = (35, 155, 235)
    r, g, b = base
    factor = 0.75 + brightness * 0.4
    return (
        min(255, int(r * factor)),
        min(255, int(g * factor)),
        min(255, int(b * factor)),
    )


# ─────────────────────── 解析/格式化 ───────────────────────


def parse_speed(s):
    """把 '92.4MB' / '512KB' / '0.00B' 转成 MB 浮点数"""
    if not s or s.strip() in ("-", "0.00B", "N/A", "", None):
        return None
    s = s.strip()
    try:
        if s.endswith("GB"):
            return float(s[:-2]) * 1024
        if s.endswith("MB"):
            return float(s[:-2])
        if s.endswith("KB"):
            return float(s[:-2]) / 1024
        if s.endswith("B"):
            return float(s[:-1]) / (1024 * 1024)
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_ms(s):
    """把 '1804ms' / '312ms(1丢)' / '-' 转成整数 ms（容忍后缀文本）"""
    if not s or s.strip() in ("-", "N/A", ""):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s))
    if not m:
        return None
    try:
        return int(float(m.group(0)))
    except (ValueError, TypeError):
        return None


def _fmt_ms(ms):
    return "-" if ms is None or not math.isfinite(ms) or ms < 0 else f"{ms:.0f}ms"


def _fmt_mb(s):
    """速度文字（MiaoKo 格式：92.4MB / 512KB / 0.00B）"""
    if s is None or not math.isfinite(s) or s < 0:
        return "-"
    if s >= 1:
        return f"{s:.2f}MB"
    kb = s * 1024
    if kb >= 1:
        return f"{kb:.2f}KB"
    return f"{s * 1024 * 1024:.2f}B"


def _type_abb(t):
    return {
        "hysteria2": "hy2",
        "wireguard": "wg",
        "shadowsocks": "ss",
        "hysteria": "hy",
        "anytls": "anytls",
        "socks5": "socks5",
    }.get(t, t[:7])


def _ping_text(r):
    """TLS RTT 列文本（v4.28.0 口径：UDP / 丢包 / 代理可达 / 超时，不把"无数据"画成空）"""
    if is_udp_node(r.node):
        return "UDP"
    if r.tcp_ping is not None:
        if r.tcp_loss:
            return f"{_fmt_ms(r.tcp_ping)}({r.tcp_loss}丢)"
        return _fmt_ms(r.tcp_ping)
    if r.tcp_probe:
        return "代理可达"
    return "超时"


def _resample_k(arr, k=10):
    """任意长度每秒速度 → k 根柱（v4.43.0 规格：每秒柱约 10 根）。

    与 report._resample_n 同义；此处保留本地实现，避免本模块反向依赖 report.py。
    """
    vals = [
        v for v in (arr or []) if isinstance(v, (int, float)) and math.isfinite(v)
    ]
    n = len(vals)
    if n == 0:
        return []
    if n <= k:
        return vals
    out = []
    for i in range(k):
        lo = int(i * n / k)
        hi = max(lo + 1, int((i + 1) * n / k))
        seg = vals[lo:hi]
        out.append(sum(seg) / len(seg) if seg else 0.0)
    return out


# ─────────────────────── 迷你柱状图（每秒速度） ───────────────────────


def draw_sparkline(
    draw, x, y, w, h, speeds, max_val=None, color_fn=sparkline_color_blue
):
    if not speeds or all(v is None or v <= 0 for v in speeds):
        return
    valid = [v if v and v > 0 else 0 for v in speeds]
    if max_val is None or max_val <= 0:
        max_val = max(valid) if valid else 1
    if max_val <= 0:
        max_val = 1
    n = len(valid)
    bar_w = max(2, w // n)
    total_bar_w = bar_w * n
    gap = max(0, (w - total_bar_w) // 2)
    rng = random.Random(42)
    for i, v in enumerate(valid):
        if v <= 0:
            continue
        ratio = min(v / max_val, 1.0)
        bar_h = max(3, int(ratio * h))
        bx = x + gap + i * bar_w
        by = y + h - bar_h
        col = color_fn(v, brightness=0.6 + rng.random() * 0.6)
        draw.rectangle([bx, by, bx + bar_w - 1, y + h - 1], fill=col)


def generate_speeds(avg_mb, count=14, seed=None):
    """按平均速度造一组示意数据（**仅演示/测试用**）。

    v4.44.0：真实报告不再调用本函数——此前每秒柱为空时会用它伪造柱形，
    等于在报告里画出并不存在的数据。保留导出仅为兼容外部引用。
    """
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random
    if avg_mb is None or avg_mb <= 0:
        return [0] * count
    return [max(0, avg_mb * rng.uniform(0.25, 1.35)) for _ in range(count)]


# ─────────────────────── 下载速度表（红粉） ───────────────────────


# 下载表列宽（表头/行共用；节点名列宽同时用于像素截断，防两处漂移）
_DL_NAME_WIDTH = 290


def draw_download_table(
    title,
    rows,
    footer_info=None,
    output_path="download_result.png",
    row_height=41,
    header_height=40,
    title_height=42,
    font_size=19,
):
    columns = [
        ("序号", 55),
        ("节点名称", _DL_NAME_WIDTH),
        ("类型", 120),
        ("HTTPS延迟", 140),
        ("平均速度", 140),
        ("最高速度", 140),
        ("每秒速度", 395),
    ]
    total_width = sum(w for _, w in columns)
    n_rows = len(rows)
    footer_height = 95 if footer_info else 0
    total_height = title_height + header_height + n_rows * row_height + footer_height
    img = Image.new("RGB", (total_width, total_height), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    font = load_font(font_size)
    font_bold = load_font(font_size, bold=True)
    font_title = load_font(font_size + 3, bold=True)
    font_footer = load_font(font_size - 4)

    draw.rectangle([0, 0, total_width, title_height], fill=(235, 235, 235))
    tb = draw.textbbox((0, 0), title, font=font_title)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text(
        ((total_width - tw) // 2, (title_height - th) // 2 - 2),
        title,
        fill=(0, 0, 0),
        font=font_title,
    )
    y_offset = title_height

    draw.rectangle(
        [0, y_offset, total_width, y_offset + header_height], fill=(232, 232, 232)
    )
    x = 0
    for col_name, col_w in columns:
        draw.rectangle(
            [x, y_offset, x + col_w, y_offset + header_height],
            outline=(195, 195, 195),
            width=1,
        )
        b = draw.textbbox((0, 0), col_name, font=font_bold)
        tw, th = b[2] - b[0], b[3] - b[1]
        draw.text(
            (x + (col_w - tw) // 2, y_offset + (header_height - th) // 2 - 2),
            col_name,
            fill=(25, 25, 25),
            font=font_bold,
        )
        x += col_w
    y_offset += header_height

    # v4.43.0 口径：柱高按"全表最大瞬时速度"归一化（此前用平均速度当基准，峰值会被顶满失真）
    all_pts = [
        s
        for r in rows
        for s in (r.get("spark") or [])
        if isinstance(s, (int, float)) and math.isfinite(s)
    ]
    global_max = max(all_pts) if all_pts else 100

    node_i = 0  # 序号只数节点行（订阅分组横条不占号）
    for ri, row in enumerate(rows):
        ry = y_offset + ri * row_height
        bg = (252, 252, 252)
        draw.rectangle([0, ry, total_width, ry + row_height], fill=bg)
        if row.get("_group"):
            # 多订阅分组横条（v4.33.0：订阅 N（M 节点））
            draw.rectangle([0, ry, total_width, ry + row_height], fill=(235, 235, 235))
            draw.text(
                (12, ry + (row_height - 22) // 2),
                row["_group"],
                fill=(60, 60, 60),
                font=font,
            )
            continue
        node_i += 1
        x = 0
        for col_name, col_w in columns:
            cell_bg = bg
            text = ""
            align = "center"
            if col_name == "序号":
                text = str(node_i)
            elif col_name == "节点名称":
                text = row.get("name", "")
                align = "left"
            elif col_name == "类型":
                text = row.get("type", "")
            elif col_name == "HTTPS延迟":
                text = row.get("https_delay", "-")
                ms = parse_ms(text)
                if ms is not None:
                    cell_bg = https_latency_color(ms)
            elif col_name == "平均速度":
                text = row.get("avg_speed", "0.00B")
                cell_bg = speed_color_red(text)
            elif col_name == "最高速度":
                text = row.get("max_speed", "0.00B")
                cell_bg = speed_color_red(text)
            elif col_name == "每秒速度":
                # v4.44.0：没有每秒数据就画空（此前会拿平均速度 + 随机数伪造柱形）
                spark = _resample_k(row.get("spark"), 10)
                if not spark and parse_speed(row.get("avg_speed", "0")) is None:
                    # 与相邻两个速度列同款"无数据"灰，避免整行看起来漏了一格
                    cell_bg = (200, 200, 200)
                draw_sparkline(
                    draw,
                    x + 3,
                    ry + 3,
                    col_w - 6,
                    row_height - 6,
                    spark,
                    max_val=global_max * 1.15,
                    color_fn=sparkline_color_red,
                )
                text = ""
            if cell_bg != bg:
                draw.rectangle([x, ry, x + col_w, ry + row_height], fill=cell_bg)
            draw.rectangle(
                [x, ry, x + col_w, ry + row_height], outline=(205, 205, 205), width=1
            )
            if text:
                b = draw.textbbox((0, 0), text, font=font)
                tw, th = b[2] - b[0], b[3] - b[1]
                tx = x + 10 if align == "left" else x + (col_w - tw) // 2
                ty = ry + (row_height - th) // 2 - 2
                draw.text((tx, ty), text, fill=(0, 0, 0), font=font)
            x += col_w
    y_offset += n_rows * row_height

    if footer_info:
        draw.rectangle([0, y_offset, total_width, total_height], fill=(232, 232, 232))
        fy = y_offset + 8
        for li, line in enumerate(footer_info):
            tx = 12
            if li == 0 and line.startswith("✅"):
                cx, cy, r = 22, fy + 10, 9
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(40, 180, 60))
                draw.line(
                    [(cx - 4, cy), (cx - 1, cy + 3), (cx + 5, cy - 4)],
                    fill=(255, 255, 255),
                    width=2,
                )
                tx = 38
                line = line[1:].lstrip()
            draw.text((tx, fy), line, fill=(55, 55, 55), font=font_footer)
            fy += 27
    img.save(output_path, "PNG")
    return output_path


# ─────────────────────── 流媒体检测表（蓝绿+状态色） ───────────────────────


def draw_streaming_table(
    title,
    rows,
    columns,
    footer_info=None,
    output_path="streaming_result.png",
    row_height=26,
    header_height=30,
    title_height=34,
    font_size=14,
    speed_color_scheme="blue",
):
    total_width = sum(c["width"] for c in columns)
    n_rows = len(rows)
    footer_height = 80 if footer_info else 0
    total_height = title_height + header_height + n_rows * row_height + footer_height
    img = Image.new("RGB", (total_width, total_height), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    font = load_font(font_size)
    font_bold = load_font(font_size, bold=True)
    font_title = load_font(font_size + 3, bold=True)
    font_footer = load_font(font_size - 3)
    speed_fn = speed_color_blue if speed_color_scheme == "blue" else speed_color_red

    draw.rectangle([0, 0, total_width, title_height], fill=(235, 235, 235))
    tb = draw.textbbox((0, 0), title, font=font_title)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text(
        ((total_width - tw) // 2, (title_height - th) // 2 - 2),
        title,
        fill=(0, 0, 0),
        font=font_title,
    )
    y_off = title_height

    draw.rectangle([0, y_off, total_width, y_off + header_height], fill=(228, 228, 228))
    x = 0
    for col in columns:
        cw = col["width"]
        draw.rectangle(
            [x, y_off, x + cw, y_off + header_height], outline=(190, 190, 190), width=1
        )
        tb = draw.textbbox((0, 0), col["name"], font=font_bold)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        draw.text(
            (x + (cw - tw) // 2, y_off + (header_height - th) // 2 - 1),
            col["name"],
            fill=(25, 25, 25),
            font=font_bold,
        )
        x += cw
    y_off += header_height

    # v4.43.0 口径：柱高按"全表最大瞬时速度"归一化
    all_pts = [
        s
        for r in rows
        for s in (r.get("spark") or [])
        if isinstance(s, (int, float)) and math.isfinite(s)
    ]
    global_max = max(all_pts) if all_pts else 100

    node_i = 0  # 序号只数节点行（订阅分组横条不占号）
    for ri, row in enumerate(rows):
        ry = y_off + ri * row_height
        bg = (252, 252, 252) if ri % 2 == 0 else (248, 248, 248)
        draw.rectangle([0, ry, total_width, ry + row_height], fill=bg)
        if row.get("_group"):
            # 多订阅分组横条（v4.33.0：订阅 N（M 节点））
            draw.rectangle([0, ry, total_width, ry + row_height], fill=(235, 235, 235))
            draw.text(
                (8, ry + (row_height - 16) // 2),
                row["_group"],
                fill=(60, 60, 60),
                font=font,
            )
            continue
        node_i += 1
        x = 0
        for col in columns:
            cw = col["width"]
            ctype = col["type"]
            cell_bg = bg
            text = ""
            align = col.get("align", "center")
            if ctype == "index":
                text = str(node_i)
            elif ctype == "name":
                text = row.get("name", "")
                align = "left"
            elif ctype == "type":
                text = row.get("type", "")
            elif ctype == "tls_rtt":
                text = row.get("tls_rtt", "-")
                ms = parse_ms(text)
                if ms is not None:
                    cell_bg = tls_rtt_color(ms)
            elif ctype == "https_delay":
                text = row.get("https_delay", "-")
                ms = parse_ms(text)
                if ms is not None:
                    cell_bg = https_latency_color(ms)
            elif ctype == "avg_speed":
                text = row.get("avg_speed", "0.00B")
                cell_bg = speed_fn(text)
            elif ctype == "max_speed":
                text = row.get("max_speed", "0.00B")
                cell_bg = speed_fn(text)
            elif ctype == "sparkline":
                # v4.44.0：没有每秒数据就画空（此前会拿平均速度 + 随机数伪造柱形）
                spark = _resample_k(row.get("spark"), 10)
                if not spark and parse_speed(row.get("avg_speed", "0")) is None:
                    # 与相邻两个速度列同款"无数据"灰
                    cell_bg = (200, 200, 200)
                draw_sparkline(
                    draw,
                    x + 2,
                    ry + 2,
                    cw - 4,
                    row_height - 4,
                    spark,
                    max_val=global_max * 1.15,
                    color_fn=sparkline_color_blue
                    if speed_color_scheme == "blue"
                    else sparkline_color_red,
                )
                text = ""
            elif ctype == "streaming":
                key = col["key"]
                text = (row.get("streaming") or {}).get(key, "")
                block = _streaming_block(text)
                if block:
                    cell_bg = block
                # v4.44.0：传 cw（函数内部自留 16px 边距）；旧写法传 cw-8 又减一次，
                # 把本该完整显示的“解锁(US)”这类文本提前加了省略号
                text = _trunc_to_width(text, cw, font)
            elif ctype == "ip_type":
                text = row.get("ip_type", "")
                block = row.get("ip_type_bg")
                if block:
                    cell_bg = block
            elif ctype == "ip_risk":
                text = row.get("ip_risk", "")
                block = row.get("ip_risk_bg")
                if block:
                    cell_bg = block
            elif ctype == "reuse":
                text = row.get("reuse", "-")
                block = row.get("reuse_bg")
                if block:
                    cell_bg = block
            elif ctype == "asn":
                text = _trunc_to_width(row.get("asn", ""), cw, font)
            elif ctype == "udp_type":
                text = row.get("udp_type", "")
            elif ctype == "text":
                text = str(row.get(col.get("key", ""), ""))
            if cell_bg != bg:
                draw.rectangle([x, ry, x + cw, ry + row_height], fill=cell_bg)
            draw.rectangle(
                [x, ry, x + cw, ry + row_height], outline=(200, 200, 200), width=1
            )
            if text:
                tb = draw.textbbox((0, 0), text, font=font)
                tw, th = tb[2] - tb[0], tb[3] - tb[1]
                if align == "left":
                    tx = x + 6
                else:
                    tx = x + (cw - tw) // 2
                ty = ry + (row_height - th) // 2 - 2
                draw.text((tx, ty), text, fill=(0, 0, 0), font=font)
            x += cw
    y_off += n_rows * row_height

    if footer_info:
        draw.rectangle([0, y_off, total_width, total_height], fill=(230, 230, 230))
        fy = y_off + 6
        for li, line in enumerate(footer_info):
            tx = 10
            if li == 0 and line.startswith("✅"):
                cx, cy, r = 18, fy + 8, 7
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(40, 180, 60))
                draw.line(
                    [(cx - 3, cy), (cx - 1, cy + 2), (cx + 4, cy - 3)],
                    fill=(255, 255, 255),
                    width=2,
                )
                tx = 32
                line = line[1:].lstrip()
            draw.text((tx, fy), line, fill=(55, 55, 55), font=font_footer)
            fy += 24
    img.save(output_path, "PNG")
    return output_path


# ─────────────────────── TestResult 适配层 ───────────────────────


def _avg_speed_text(r):
    """平均速度单元格文本（v4.28.0 口径：无速度时如实显示失败原因）"""
    if r.speed is not None:
        return _fmt_mb(r.speed)
    return _trunc_width(r.error, 10) if r.error else "-"


def _max_speed_text(r):
    """最高速度单元格文本"""
    return _fmt_mb(r.max_speed if r.max_speed is not None else r.speed)


def build_download_rows(results, name_width=None, font=None):
    """TestResult 列表 → 下载速度表 rows

    name_width + font 给定时按**像素**截断节点名：下载表名称列宽固定，
    按字符数截断（旧行为）会让 26 个全角字符（约 494px）溢出到隔壁列。
    """
    if font is not None and name_width:
        trunk = lambda s: _trunc_to_width(s, name_width, font)
    else:
        trunk = lambda s: _fmt_name(s, 26)
    return [
        {
            "name": trunk(_flag_to_text(r.node.name)),
            "type": _type_abb(r.node.type),
            "https_delay": _fmt_ms(r.http_latency),
            # v4.28.0：无速度数据时如实显示失败原因（节点不可达/下载失败/速度过低…）
            "avg_speed": _avg_speed_text(r),
            "max_speed": _max_speed_text(r),
            "spark": [
                s
                for s in (r.speed_per_sec or [])
                if isinstance(s, (int, float)) and math.isfinite(s)
            ],
        }
        for r in results
    ]


# 流媒体列展示名映射（列标题用中文短名）
_STREAM_NAME = {
    "youtube": "YouTube",
    "netflix": "Netflix",
    "disney": "Disney+",
    "chatgpt": "OpenAI",
    "claude": "Claude",
    "gemini": "Gemini",
    "perplexity": "Perplexity",
    "deepseek": "DeepSeek",
    "moonshot": "Kimi",
    "abema": "AbemaTV",
    "bilibili_tw": "B站港澳台",
    "dazn": "Dazn",
    "hbomax": "HboMax",
    "tiktok": "TikTok",
    "spotify": "Spotify",
    "primevideo": "PrimeVideo",
    "max": "Max",
    "appletv": "AppleTV",
    "steam": "Steam",
    "projectsekai": "ProjectSekai",
}


# 正常流媒体列头缩写（保留 MiaoKo 演示的分栏风格）
def _stream_col_name(sid):
    if sid in _STREAM_NAME:
        return _STREAM_NAME[sid]
    # 未收录的 id 回退到 config 服务表里的显示名（避免表头出现 crunchyroll 这类裸 id）
    for svc in FULL_STREAMING_SERVICES:
        if svc.get("id") == sid:
            return svc.get("name") or sid
    return sid


def _ip_type_text(ip_info):
    d = ip_info
    if d.get("error") or not d.get("ip"):
        return "-"
    # v4.19.0 口径：核心风控字段（机房/代理/移动）全为 None = 数据源没有风控数据，
    # 不能编造成"家宽 IP"（report._ctxt 同口径返回 "--"）
    if (
        d.get("is_datacenter") is None
        and d.get("is_proxy") is None
        and d.get("is_mobile") is None
    ):
        return "-"
    if d.get("is_tor"):
        return "Tor"
    if d.get("is_proxy") or d.get("is_vpn"):
        return "代理"
    if d.get("is_datacenter"):
        return "商宽/机房IP"
    if d.get("is_mobile"):
        return "移动网络IP"
    return "家宽IP"


def _ip_risk_text(ip_info):
    d = ip_info
    if d.get("error") or not d.get("ip"):
        return "-"
    sc = d.get("risk_score")
    if sc is None:
        return "-"
    return f"{'LOW' if sc < 20 else ('MEDIUM' if sc < 60 else 'HIGH')}({sc})"


def _ip_type_color(ip_info):
    """IP 类型背景色（家宽→浅绿 / 商宽机房→柔黄 / 代理VPNTor→柔粉；无数据 → None）

    v4.44.0：流媒体表的 IP 类型列此前只上文字不上色，风险高低没法一眼看（旧自绘版本有）。
    """
    d = ip_info
    if d.get("error") or not d.get("ip"):
        return None
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


def _ip_risk_color(ip_info):
    """IP 风险背景色（低<20→绿 / 中<60→黄 / 高→柔粉；无数据 → None）"""
    d = ip_info
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


def _reuse_text(ip_info):
    """复用档位文本（v4.20.0 四档：完全/中转/落地复用）"""
    return (ip_info or {}).get("reuse") or "-"


def _reuse_color(ip_info):
    """复用背景色（完全→深红 / 中转→深黄 / 落地→深青）；无数据 → None

    v4.44.0：复用列在委托渲染后曾整列丢失，这里补回（仅在有复用数据时建列）。
    """
    reuse = (ip_info or {}).get("reuse")
    key = {"完全复用": "full", "中转复用": "relay", "落地复用": "landing"}.get(
        str(reuse) if reuse else ""
    )
    return REUSE_COLORS.get(key) if key else None


def _asn_text(ip_info):
    asn = ip_info.get("asn") or ""
    org = ip_info.get("org") or ""
    return (f"{asn} {org}" if asn and org else (asn or org or "-"))[:35]


def _measure(text, font):
    if not text:
        return 0
    try:
        return int(font.getlength(text))
    except Exception:
        return len(text) * 14


def _fmt_name(name, limit=24):
    """节点名按字符数截断（防超长撑破列）"""
    name = name or ""
    return name if len(name) <= limit else name[:limit].rstrip() + "…"


def build_streaming_rows(results, name_width=None, font=None):
    if font is not None and name_width:
        trunk = lambda s: _trunc_to_width(s, name_width, font)
    else:
        trunk = lambda s: _fmt_name(s, 26)
    return [
        {
            "name": trunk(_flag_to_text(r.node.name)),
            "type": _type_abb(r.node.type),
            "tls_rtt": _ping_text(r),
            "https_delay": _fmt_ms(r.http_latency),
            "avg_speed": (
                _fmt_mb(r.speed)
                if r.speed is not None
                else (_trunc_width(r.error, 10) if r.error else "-")
            ),
            "max_speed": _fmt_mb(r.max_speed if r.max_speed is not None else r.speed),
            "ip_type": _ip_type_text(r.ip_info),
            "ip_risk": _ip_risk_text(r.ip_info),
            "ip_type_bg": _ip_type_color(r.ip_info),
            "ip_risk_bg": _ip_risk_color(r.ip_info),
            "reuse": _reuse_text(r.ip_info),
            "reuse_bg": _reuse_color(r.ip_info),
            "asn": _asn_text(r.ip_info),
            "udp_type": _udp_type_text(r.node),
            "spark": [
                s
                for s in (r.speed_per_sec or [])
                if isinstance(s, (int, float)) and math.isfinite(s)
            ],
            "streaming": r.streaming or {},
        }
        for r in results
    ]


def _collect_stream_ids(results):
    ids = []
    for r in results:
        for k in r.streaming or {}:
            if k not in ids:
                ids.append(k)
    # 按 MiaoKo 常见顺序排：Netflix/YouTube/Disney+ 优先
    order = [
        "netflix",
        "youtube",
        "disney",
        "chatgpt",
        "abema",
        "bilibili_tw",
        "dazn",
        "hbomax",
        "tiktok",
        "spotify",
        "primevideo",
        "projectsekai",
    ]
    return sorted(ids, key=lambda i: order.index(i) if i in order else 99)


def _trunc_to_width(name, max_w, font):
    """按像素宽截断节点名（二分：适合 name_width 列）"""
    if _measure(name, font) <= max_w - 16:
        return name
    lo, hi = 0, len(name)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _measure(name[:mid] + "…", font) <= max_w - 16:
            lo = mid
        else:
            hi = mid - 1
    return name[:lo] + "…" if lo < len(name) else name


def build_streaming_columns(results, include_speed=True, font_size=14):
    """按实际数据构建流媒体表列配置（列宽自适应内容）"""
    font = load_font(font_size)
    pad = 16

    def cw(title, values, cap=220):
        w = _measure(title, font)
        for v in values:
            w = max(w, _measure(v if v else "", font))
        return max(40, min(cap, w + pad))

    names = [_flag_to_text(r.node.name) for r in results]
    name_w = cw("节点名称", names)
    has_ip = any((r.ip_info or {}).get("ip") for r in results)
    cols = [
        {"name": "序号", "width": 40, "type": "index"},
        {"name": "节点名称", "width": name_w, "type": "name"},
        {
            "name": "类型",
            "width": cw("类型", [_type_abb(r.node.type) for r in results]),
            "type": "type",
        },
        {
            "name": "TLS RTT",
            # v4.44.0：按**实际单元格文本**（含“(1丢)”后缀）量宽，旧写法用 _fmt_ms 量，
            # 导致带丢包后缀的节点文字被硬裁切
            "width": cw("TLS RTT", [_ping_text(r) for r in results]),
            "type": "tls_rtt",
        },
        {
            "name": "HTTPS延迟",
            "width": cw("HTTPS延迟", [_fmt_ms(r.http_latency) for r in results]),
            "type": "https_delay",
        },
    ]
    if include_speed:
        cols += [
            {
                "name": "平均速度",
                # v4.44.0：同样按实际单元格文本量宽（无速度时显示的是失败原因，可能更长）
                "width": cw("平均速度", [_avg_speed_text(r) for r in results]),
                "type": "avg_speed",
            },
            {
                "name": "最高速度",
                "width": cw(
                    "最高速度",
                    [_max_speed_text(r) for r in results],
                ),
                "type": "max_speed",
            },
            {"name": "每秒速度", "width": 100, "type": "sparkline"},
        ]
    if has_ip:
        cols += [
            {
                "name": "IPtype",
                "width": cw("IPtype", [_ip_type_text(r.ip_info) for r in results]),
                "type": "ip_type",
            },
            {
                "name": "IPrisk",
                "width": cw("IPrisk", [_ip_risk_text(r.ip_info) for r in results]),
                "type": "ip_risk",
            },
        ]
    # v4.44.0：复用列（v4.20.0 四档检测）——有复用数据时才建列
    if any((r.ip_info or {}).get("reuse") for r in results):
        cols.append(
            {
                "name": "复用",
                "width": cw("复用", [_reuse_text(r.ip_info) for r in results]),
                "type": "reuse",
            }
        )
    for sid in _collect_stream_ids(results):
        vals = [(r.streaming or {}).get(sid, "") for r in results]
        title = _stream_col_name(sid)
        cols.append(
            {"name": title, "width": cw(title, vals), "type": "streaming", "key": sid}
        )
    if has_ip:
        cols.append(
            {
                "name": "ASN",
                # ASN 列单词较长（AS45102 + org），列宽上限放宽到 260，减少密集省略号
                "width": cw("ASN", [_asn_text(r.ip_info) for r in results], cap=260),
                "type": "asn",
            }
        )
    cols.append(
        {
            "name": "UDP类型",
            "width": cw("UDP类型", [_udp_type_text(r.node) for r in results]),
            "type": "udp_type",
        }
    )
    return cols


# ─────────────────────── 顶层入口 ───────────────────────

_MODE_NAME = {
    "speed": "下载速度",
    "basic": "下载速度",
    "normal": "标准测试",
    "full": "完整测速",
    "streaming": "流媒体",
    "streaming_ai": "AI流媒体",
    "streaming_all": "全部流媒体",
    "quick": "快速检测",
}
_SORT_NAME = {
    "none": "订阅顺序",
    "default": "订阅顺序",
    "max_desc": "最大速度降序",
    "max_asc": "最大速度升序",
    "avg_desc": "平均速度降序",
    "avg_asc": "平均速度升序",
    "name_asc": "名称A→Z",
    "name_desc": "名称Z→A",
}


def _reach_stats(results):
    """可达统计（v4.28.0 口径：TCP 握手成功或隧道探测可达）+ 平均延迟 + UDP 节点数"""
    tcp_ok = [r.tcp_ping for r in results if r.tcp_ping is not None]
    succ = sum(1 for r in results if r.tcp_ping is not None or r.tcp_probe)
    avg = (sum(tcp_ok) / len(tcp_ok)) if tcp_ok else 0.0
    udp_n = sum(1 for r in results if is_udp_node(r.node))
    return succ, avg, udp_n


def _with_group_markers(rows, results):
    """多订阅时在行序列里插入分组横条（rows 与 results 顺序一一对应，v4.33.0 订阅分组）"""
    subs = sorted(
        {r.node.sub_index for r in results if r.node.sub_index is not None}
    )
    if len(subs) < 2:
        return rows
    out = []
    for si in subs:
        # 不用 zip（避免 strict= 提示——项目声明支持 Python 3.9）
        grp = [rows[i] for i, r in enumerate(results) if r.node.sub_index == si]
        if not grp:
            continue
        out.append({"_group": f"订阅 {si + 1}（{len(grp)} 节点）"})
        out.extend(grp)
    rest = [rows[i] for i, r in enumerate(results) if r.node.sub_index is None]
    if rest:
        out.append({"_group": f"未知订阅（{len(rest)} 节点）"})
        out.extend(rest)
    return out


def render_miaoko_report(
    results,
    mode,
    total_time,
    sort_by="default",
    display_mode=None,
    run_bytes=None,
    truncated=None,
    output_path="report.png",
):
    """按模式渲染 MiaoKo 风格报告，返回输出路径。

    results: list[TestResult]（**已排序**——调用方负责；本函数不再排序）
    mode: speed/basic/normal/full/streaming/streaming_ai/streaming_all/quick
    truncated: (已显示行数, 总行数)，用于页脚提示只画了前 N 行（None=未截断）
    """
    display_mode = display_mode or mode
    n = len(results)
    mode_name = _MODE_NAME.get(display_mode, display_mode)
    sort_name = _SORT_NAME.get(sort_by, sort_by)
    subtitle = (
        "speed - 下载速度"
        if display_mode in ("speed", "basic")
        else "test - 自定义测试"
    )
    title = f"MiaoKo 风格 | {mode_name} | {subtitle}"

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    tz = time.strftime("%Z") or "本地时间"
    flow = f", 本次实测下载 {_fmt_bytes(run_bytes)}" if run_bytes else ""
    succ, avg_ms, udp_n = _reach_stats(results)
    # v4.28.0 口径的行1：quick 是并行近似测速，不能声称"已核实 TLS 证书"
    ftr1 = (
        "✅ 快速模式（并行近似测速）"
        if display_mode == "quick"
        else "✅ 已核实 TLS 证书。TLS RTT 为单次数据交换延迟，HTTPS Ping 为单次请求体感延迟。"
    )
    # v4.32.0 口径的行2：可达统计（旧写法是写死的 n/n，死节点也算可达）
    ftr2 = f"节点: {succ}/{n} 可达 | 平均延迟: {avg_ms:.0f}ms"
    if udp_n:
        ftr2 += f" | UDP节点: {udp_n} 个(经HTTP实测)"
    ftr2 += f" | 排序={sort_name}"
    ftr3 = f"测试时间: {now} ({tz}){flow}"
    if truncated:
        ftr3 += f" | 仅显示前 {truncated[0]}/{truncated[1]} 节点"
    ftr3 += f" | 引擎=speed_test.py v{VERSION}, 本测试为试验性结果，仅供参考。"
    footer = [ftr1, ftr2, ftr3]

    if display_mode in ("speed", "basic", "quick"):
        rows = build_download_rows(results, name_width=_DL_NAME_WIDTH, font=load_font(19))
        draw_download_table(
            title,
            _with_group_markers(rows, results),
            footer_info=footer,
            output_path=output_path,
            row_height=41,
        )
    else:
        cols = build_streaming_columns(results, include_speed=True)
        name_w = next(c["width"] for c in cols if c["type"] == "name")
        rows = build_streaming_rows(results, name_width=name_w, font=load_font(14))
        draw_streaming_table(
            title,
            _with_group_markers(rows, results),
            cols,
            footer_info=footer,
            output_path=output_path,
            row_height=26,
        )
    return output_path


def _fmt_bytes(b):
    if b is None:
        return "-"
    b = float(b)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.2f}{unit}"
        b /= 1024
    return f"{b:.2f}PB"


__all__ = [
    "load_font",
    "https_latency_color",
    "tls_rtt_color",
    "speed_color_red",
    "speed_color_blue",
    "streaming_color",
    "_streaming_block",
    "sparkline_color_red",
    "sparkline_color_blue",
    "parse_speed",
    "parse_ms",
    "draw_sparkline",
    "draw_download_table",
    "draw_streaming_table",
    "build_download_rows",
    "build_streaming_rows",
    "build_streaming_columns",
    "render_miaoko_report",
    "_ping_text",
    "_resample_k",
    "_ip_type_color",
    "_ip_risk_color",
    "_reuse_text",
    "_reuse_color",
    "_reach_stats",
    "_with_group_markers",
    "_DL_NAME_WIDTH",
]
