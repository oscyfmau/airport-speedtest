#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用工具：URL 遮蔽 / 异常安全化 / 编码 / SSL / 显示宽度 / 可选依赖探测 / 进度刷新"""
import asyncio
import base64
import re
import ssl

HAS_CLOUDSCRAPER = False


try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    pass


HAS_YTDLP = False


try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    pass


_SENSITIVE_PARAMS = {"token", "password", "passwd", "key", "secret", "auth",
                     "sub", "subid", "code", "id",
                     "sid", "user", "username", "pass", "access_token",
                     "refresh_token", "token_type", "api_key", "apikey",
                     "secret_key", "private_key", "client_secret",
                     "session", "sessionid", "cookie"}

_AUTH_INFO_RE = re.compile(r"^(https?://)([^/@]+)@", re.IGNORECASE)  # v4.27.0：兼容大写 scheme


def _mask_value_query(v: str) -> str:
    """遮蔽值内嵌套的 query/分号参数（v4.27.0：如 ?a=1?token=SECRET 的 value "1?token=SECRET"）"""
    sep = "?" if "?" in v else ";"
    parts = v.split(sep)
    for i in range(1, len(parts)):
        seg = parts[i]
        if "=" in seg:
            k, _ = seg.split("=", 1)
            if k.lower() in _SENSITIVE_PARAMS:
                parts[i] = f"{k}=***"
    return sep.join(parts)


def _mask_url(url: str) -> str:
    """遮蔽 URL 中敏感信息（query 凭据参数 + 权威段 basic-auth + path 末段疑似凭据），
    用于打印与日志"""
    # 权威段 basic-auth：https://user:pass@host → https://user:***@host
    m = _AUTH_INFO_RE.match(url)
    if m:
        userinfo = m.group(2)
        if ":" in userinfo:
            user, _ = userinfo.rsplit(":", 1)
            url = f"{m.group(1)}{user}:***@{url[m.end():]}"
        else:
            url = f"{m.group(1)}***@{url[m.end():]}"
    if "?" in url:
        base, qs = url.split("?", 1)
    else:
        base, qs = url, ""
    # path 末段疑似 token（长度≥16 且无 "."）时遮蔽
    segs = base.split("/")
    if len(segs) >= 2 and segs[-1] and len(segs[-1]) >= 16 and "." not in segs[-1]:
        segs[-1] = "***"
        base = "/".join(segs)
    if not qs:
        return base
    parts = []
    for p in re.split(r"[&;]", qs):  # v4.27.0：";" 分隔参数一并处理
        if "=" in p:
            k, v = p.split("=", 1)
            if k.lower() in _SENSITIVE_PARAMS:
                v = "***"
            elif "?" in v or ";" in v:
                v = _mask_value_query(v)
            parts.append(f"{k}={v}")
        else:
            parts.append(p)
    return f"{base}?{'&'.join(parts)}"


_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


_URL_REL_RE = re.compile(r"(url[:=]\s*)(\S+)")


def _safe_exc_str(e: BaseException) -> str:
    """异常文本内的 URL 统一过 _mask_url（requests/aiohttp 异常常携带完整 URL
    或 "url: /path?token=..." 相对形式，防止 token 经异常消息泄漏）"""
    try:
        s = str(e)
        s = _URL_IN_TEXT_RE.sub(lambda m: _mask_url(m.group(0)), s)
        s = _URL_REL_RE.sub(lambda m: m.group(1) + _mask_url(m.group(2)), s)
        return s
    except Exception:
        return str(e)


_FLAG_PAIR_RE = re.compile(r"([\U0001F1E6-\U0001F1FF]){2}")


def _flag_to_text(s: str) -> str:
    """控制台安全化显示名：国旗 emoji 对 → [国家代码]，其余 astral-plane 字符删除。

    仅用于控制台与进度条显示；节点原名、文件日志、PNG 报告、JSON 均不变。
    """
    if not s:
        return s

    def _pair(m):
        a, b = m.group(0)
        return f"[{chr(ord(a) - 0x1F1E6 + 65)}{chr(ord(b) - 0x1F1E6 + 65)}]"

    new = _FLAG_PAIR_RE.sub(_pair, s)
    new = re.sub(r"[\U00010000-\U0010FFFF]", "", new)
    return new.strip() if new != s else s


def _no_verify_ssl() -> ssl.SSLContext:
    """构建跳过证书校验的 SSL 上下文（本机经 mihomo 隧道访问目标站用）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _remove_prefix(s: str, prefix: str) -> str:
    """移除字符串前缀（兼容 Python 3.8+）"""
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def b64decode_pad(s: str) -> bytes:
    """Base64 解码，自动处理 padding（v4.27.0：清理全部空白，支持多行 base64）"""
    s = re.sub(r"\s+", "", s)
    # 处理 URL-safe base64
    s = s.replace('-', '+').replace('_', '/')
    s += '=' * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s)


def _str_width(s: str) -> int:
    """计算字符串在终端中的显示宽度（CJK/全角=2，半角=1）"""
    import unicodedata
    w = 0
    for c in s:
        cp = ord(c)
        if 0x2500 <= cp <= 0x257F:
            w += 1  # 方框绘图字符是半角
        elif cp > 127:
            # 按 Unicode 东亚洲宽度判定（é/ü 等窄字符计 1）
            w += 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        else:
            w += 1
    return w


def _pad_right(text: str, width: int) -> str:
    """在文本右侧填充空格到指定显示宽度"""
    return text + " " * max(0, width - _str_width(text))


def _trunc_width(text: str, width: int, suffix: str = "…") -> str:
    """按显示宽度截断字符串（CJK 按 2 宽计），超出加省略号"""
    if _str_width(text) <= width:
        return text
    out = ""
    w = 0
    for c in text:
        cw = _str_width(c)
        if w + cw > width - _str_width(suffix):
            break
        out += c
        w += cw
    return out + suffix


def _fmt_size(n_bytes: float) -> str:
    """字节数人性化显示（B/KB/MB/GB，1 位小数）"""
    try:
        n = float(n_bytes)
    except (TypeError, ValueError):
        return "--"
    if n < 1024:
        return f"{n:.0f}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f}MB"
    return f"{n / 1024 / 1024 / 1024:.1f}GB"


def _sanitize_surrogates(s: str) -> str:
    """把字符串中的非法 surrogate（U+D800-DFFF）替换为 U+FFFD

    来源：管道输入/异常文本在 locale 非 UTF-8 且 errors=surrogateescape
    解码时可能产生；不净化会导致控制台/JSONL 写 UTF-8 时 UnicodeEncodeError。
    """
    if s and any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        return s.encode("utf-8", "replace").decode("utf-8")
    return s


async def _pbar_ticker(pbar, stop_event: asyncio.Event) -> None:
    """每秒刷新一次进度条显示（cmd 控制台每秒更新；串行阶段用）

    v4.16.0 起定义在 utils（零依赖层）：tester/streaming/ip_quality/webpage 共用，
    避免 streaming↔tester 循环导入（v4.10 模块化回归：streaming 等引用未定义名）。
    """
    try:
        while not stop_event.is_set():
            pbar.refresh()
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        pass

__all__ = ['HAS_CLOUDSCRAPER', 'HAS_YTDLP', '_SENSITIVE_PARAMS', '_mask_url', '_URL_IN_TEXT_RE', '_URL_REL_RE', '_safe_exc_str', '_FLAG_PAIR_RE', '_flag_to_text', '_no_verify_ssl', '_remove_prefix', 'b64decode_pad', '_str_width', '_pad_right', '_trunc_width', '_fmt_size', '_sanitize_surrogates', '_pbar_ticker']
