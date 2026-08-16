#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流媒体解锁检测：专用检测器 / 通用检测 / 批量运行"""
import asyncio
import base64
import re
from urllib.parse import unquote

import aiohttp
from tqdm import tqdm

from .config import *
from .engine import *
from .logging_setup import *
from .models import *
from .utils import *

async def check_youtube(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 YouTube Premium 解锁，如果 Premium 送中则回退到普通 YouTube

    v4.17.0：修复三处误判——
    1) 送中判定不再用 `"www.google.cn" in text`（新页面变体的广告配置
       `https://www.google.cn/pagead/lvz?...` 与地区无关，已实测间歇出现），
       改为：请求重定向到 google.cn / 页面含非 pagead 的 google.cn 链接 /
       visitorData 内嵌地区码 == CN；
    2) 地区提取优先 visitorData（base64url+protobuf，内嵌 `\\x0a\\x02<CC>`，
       IP 地理定位，不受页面变体影响），回退 countryCode / INNERTUBE_CONTEXT_GL
       （新页面变体 GL 固定 US，仅作最后兜底）；
    3) countryCode 在新页面变体中已消失，旧正则不再命中。
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,en;q=0.9",
        }
        async with session.get(
            "https://www.youtube.com/premium", proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            status = resp.status
            text = await resp.text()
            region = _extract_yt_region(text)
            # 送中检测：真重定向 / 页面指向 google.cn 的链接（非广告位 URL）/ 地区码 CN
            sent_to_cn = (
                "google.cn" in str(resp.url)
                or re.search(r'href=["\']https?://www\.google\.cn', text) is not None
                or re.search(r"www\.google\.cn/(?!pagead)", text) is not None
                or region == "CN"
            )
            if sent_to_cn:
                # 回退检测普通 YouTube 是否可访问
                try:
                    async with session.get("https://www.youtube.com", proxy=proxy,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT)) as r2:
                        if r2.status == 200:
                            return "可用(CN)"
                except Exception:
                    pass
                return "送中(CN)"
            # 区域不可用
            if "Premium is not available in your country" in text:
                return "失败(区域限制)"
            # ad-free 标识=解锁
            if "ad-free" in text or "YouTube and YouTube Music ad-free" in text:
                if region:
                    return f"解锁({region})"
                return "解锁(未知)"
            # 有地区代码但无 ad-free → 无 Premium 解锁但 YouTube 可访问
            if region:
                return f"可用({region})"
            # 200 但无任何可识别特征（consent/登录墙等变体）→ 至少可达
            if status == 200:
                return "可用"
            # v4.27.0：暴露真实状态码（旧实现统一"失败(无Premium标识)"掩盖 403/风控）
            return f"失败(HTTP {status})"
    except Exception as e:
        return f"错误({type(e).__name__})"


def _extract_yt_region(text: str) -> str:
    """从 YouTube 页面提取地区码（优先级：visitorData > countryCode > GL）

    visitorData 为 base64url（可能 URL 编码 + JSON 转义），内部是 protobuf 结构，
    地区码以 `\\x0a\\x02<CC>` 形式内嵌，来自 Google 对出口 IP 的地理定位，
    不受页面变体（countryCode 字段消失 / GL 固定 US）影响，2026-08 实测可靠。
    """
    region = ""
    m = re.search(r'"visitorData"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        try:
            vd = unquote(m.group(1).encode("utf-8").decode("unicode_escape"))
            raw = base64.urlsafe_b64decode(vd + "=" * (-len(vd) % 4))
            mm = re.search(rb"\x0a\x02([A-Z]{2})", raw)
            if mm:
                region = mm.group(1).decode()
        except Exception:
            pass
    if not region:
        m = re.search(r'"countryCode"\s*:\s*"([A-Z]{2})"', text)
        if m:
            region = m.group(1)
    if not region:
        m = re.search(r'"INNERTUBE_CONTEXT_GL"\s*:\s*"([A-Z]{2})"', text)
        if m:
            region = m.group(1)
    return region


async def check_netflix(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Netflix 解锁（参考 RegionRestrictionCheck）

    v4.14.0：title 探测异常（连接/解析错误，如响应头超 aiohttp 限制）不再直接判
    "错误(连接失败)"——回退首页可达性判定（200 + 区域从重定向 URL 提取，如 /hk-en/）。
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async def _check(url: str) -> str:
            try:
                async with session.get(url, proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                    allow_redirects=True,
                ) as r:
                    if r.status in (403, 404):
                        return "blocked"  # 区域限制/不存在
                    if r.status != 200:
                        return "error"    # v4.27.0：5xx 等瞬时错误归"错误"类（触发重试一次）
                    t = await r.text()
                    if "Not Available" in t or "not available" in t:
                        return "blocked"
                    region = ""
                    m = re.search(r'"country"\s*:\s*"([A-Z]{2})"', t)
                    if m:
                        region = m.group(1)
                    return f"ok:{region}" if region else "ok"
            except Exception:
                return "error"

        r1 = await _check("https://www.netflix.com/title/81280792")  # 自制剧
        r2 = await _check("https://www.netflix.com/title/70143836")  # 非自制剧

        if r1.startswith("ok") and r2.startswith("ok"):
            region = r1.split(":")[1] if ":" in r1 else r2.split(":")[1] if ":" in r2 else ""
            return f"解锁({region})" if region else "解锁"
        elif r1.startswith("ok") and not r2.startswith("ok"):
            return "仅自制剧"
        elif "error" in (r1, r2):
            # title 探测异常（响应头过大/连接瞬断等）→ 首页可达性兜底 + URL 区域
            try:
                async with session.get(
                    "https://www.netflix.com/", proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                    allow_redirects=True,
                ) as r:
                    if r.status == 200:
                        region = ""
                        m = re.search(r"/[a-z]{2}-en/?", str(r.url))
                        if m:
                            region = m.group(0).strip("/").split("-")[0].upper()
                        return f"可用({region})" if region else "可用"
                    return "错误(连接失败)"
            except Exception:
                return "错误(连接失败)"
        else:
            return "失败"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_disney(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Disney+（跟进重定向；区域不可用页/无订阅文案不算解锁）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with session.get(
            "https://www.disneyplus.com/", proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            final_url = str(resp.url)
            if resp.status == 200:
                # 区域不可用/无订阅落地页（URL 或页面文案）不算解锁
                if any(k in final_url.lower() for k in ("not-available", "unavailable")):
                    return "失败(区域不可用)"
                text = await resp.text()
                if any(kw in text for kw in ("This title is not available",
                                              "not available in your country",
                                              "choose your region")):
                    return "失败(区域不可用)"
                return "解锁"
            elif resp.status == 403:
                return "封锁"
            return f"({resp.status})"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_chatgpt(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 ChatGPT（v4.33.0 重写：api.openai.com 区域判别为主，网页探测链兜底；
    v4.34.0 修正：429/5xx 等非 403 状态与 claude/perplexity 同义=区域放行，
    网页链兜底不再产出"封锁"误报）

    背景（2026-08 实测，用户订阅 2 份 12 节点）：chatgpt.com / chat.openai.com /
    ios.chat.openai.com 对数据中心 IP + 非浏览器 TLS 一律返回 CF 403（挑战页或
    {"type":"dc"} 风控 JSON），无法区分"区域封锁"与"机器人风控"，导致 HK/TW/SG/JP/US
    等支持区域的节点被误报为"封锁"。
    api.openai.com 无此风控：无效 key → 401 invalid_request_error 等业务错误码
    = 已到达 API = 区域放行；不支持的国家 → 403 且 body 含 unsupported_country
    = 区域封锁。
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with session.get(
                "https://api.openai.com/v1/models", proxy=proxy,
                headers={**headers, "Authorization": "Bearer x"},
                timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),  # v4.38.0：统一引用常量
                allow_redirects=False) as r:
            if r.status == 403:
                # 不支持的国家/地区（OpenAI 以 403 unsupported_country 拒绝整个区域）
                return "封锁"
            # 其余任何已到达状态（401 无效 key / 400 / 429 / 5xx 等）＝区域放行。
            # v4.34.0：与 check_claude/check_perplexity 语义统一——此前 429/5xx 落回
            # 网页链会因 CF 风控误报"封锁"，同节点三列自相矛盾
            region = ""
            try:
                async with session.get(
                        "https://chat.openai.com/cdn-cgi/trace", proxy=proxy,
                        headers=headers, timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),  # v4.38.0：统一引用常量
                        allow_redirects=True) as t2:
                    for line in (await t2.text()).splitlines():
                        if line.startswith("loc="):
                            region = line[4:].strip()
                            break
            except Exception:
                pass
            return f"解锁({region})" if region else "解锁"
    except Exception:
        pass

    # ---- 旧网页探测链（保留：api.openai.com 网络不可达时的兜底；
    #      v4.34.0 起不再产出"封锁"，CF 403 无法区分区域封锁与机器人风控 → "未知"） ----

    async def _probe(url: str) -> tuple[int, str]:
        """探测一个端点，返回 (status, text)"""
        try:
            async with session.get(url, proxy=proxy, headers=headers,
                timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),  # v4.38.0：统一引用常量
                allow_redirects=True) as r:
                t = await r.text()
                return r.status, t
        except Exception:
            return 0, ""

    # 优先探测 chatgpt.com 主站
    status1, _ = await _probe("https://chatgpt.com/")
    if status1 == 200:
        return "解锁"

    # 再试 chat.openai.com favicon
    status2, _ = await _probe("https://chat.openai.com/favicon.ico")
    if status2 == 200:
        return "解锁"

    # 再试 cdn-cgi/trace（仅用于判定"连接是否彻底失败"）
    status3, _ = await _probe("https://chat.openai.com/cdn-cgi/trace")

    # 三个端点全部网络失败 → 连接失败（触发"错误"类结果重试）
    if status1 == 0 and status2 == 0 and status3 == 0:
        return "错误(连接失败)"
    # 有 HTTP 响应但非 200：CF 已拦截（可能是区域封锁，也可能是数据中心风控），
    # 与 v4.27.0 的教训一致（trace loc ≠ OpenAI 放行），无法判定 → 未知
    return "未知"


async def check_claude(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Claude（v4.33.0 新增专用检测器；v4.34.0 修正网页兜底误报）

    背景（2026-08 实测）：claude.ai 网页对数据中心 IP + 非浏览器 TLS 返回 CF 403
    挑战页（Just a moment...），支持区域的节点被误报"封锁"。
    api.anthropic.com 无此风控：区域放行 → 405/400/401 等 API 业务错误（已到达 API）；
    不支持区域 → 403 CF 拦截页。403 → 封锁；其余任何已到达状态 → 可用。
    """
    try:
        async with session.get(
                "https://api.anthropic.com/v1/messages", proxy=proxy,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                         "x-api-key": "x", "anthropic-version": "2023-06-01"},
                timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),  # v4.38.0：统一引用常量
                allow_redirects=False) as r:
            if r.status == 403:
                return "封锁"
            return "可用"  # 已到达 Anthropic API = 区域放行（405/400/401/429/5xx 等）
    except Exception:
        pass
    # 兜底：旧通用网页探测。v4.34.0：claude.ai 网页同受 CF 机器人风控，
    # 403 无法区分"区域封锁"与"数据中心风控"，判"封锁"降级为"未知"防误报
    res = await check_generic(session, proxy, "https://claude.ai", "Claude")
    return "未知" if res == "封锁" else res


async def check_perplexity(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Perplexity（v4.33.0 新增专用检测器；v4.34.0 修正网页兜底误报）

    背景（2026-08 实测）：www.perplexity.ai 网页对数据中心 IP + 非浏览器 TLS 返回
    CF 403 挑战页，支持区域的节点被误报"封锁"。
    api.perplexity.ai 无此风控：区域放行 → 401 invalid api key 等业务错误（已到达 API）；
    不支持区域 → 403 CF 拦截页。403 → 封锁；其余任何已到达状态 → 可用。
    """
    try:
        async with session.post(
                "https://api.perplexity.ai/chat/completions", proxy=proxy,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                         "Authorization": "Bearer x",
                         "Content-Type": "application/json"},
                data="{}",
                timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),  # v4.38.0：统一引用常量
                allow_redirects=False) as r:
            if r.status == 403:
                return "封锁"
            return "可用"  # 已到达 Perplexity API = 区域放行（401/400/429/5xx 等）
    except Exception:
        pass
    # 兜底：旧通用网页探测。v4.34.0：www.perplexity.ai 网页同受 CF 机器人风控，
    # 403 无法区分"区域封锁"与"数据中心风控"，判"封锁"降级为"未知"防误报
    res = await check_generic(session, proxy, "https://www.perplexity.ai", "Perplexity")
    return "未知" if res == "封锁" else res


async def check_generic(session: aiohttp.ClientSession, proxy: str, url: str, name: str) -> str:
    """通用检测（跟进重定向，最终 2xx/3xx 算可用；4xx/5xx 走 403 特判或按状态码返回）

    403 判定（v4.14.0 收紧）：先查挑战页特征（Cloudflare/JS 挑战/人机验证等变体）→ 封锁；
    再查页面 title 是否含平台名（挑战页 title 为 "Just a moment..." 等，不匹配）→ 可用；
    最后大页面结构兜底（>15KB 且含前端框架特征）→ 可用；其余 403 一律封锁——
    不再仅凭页面含 "<html" 判可用（挑战页几乎都含，会误判）。
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with session.get(
            url, proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            status = resp.status
            # 有些服务返回 3xx/404 但也算可访问（如某些仅登录后可见的平台）
            # v4.38.0：allow_redirects=True 下最终状态永不为 3xx，移除死分支
            if status in (200, 201, 202, 204):
                return "可用"
            if status == 403:
                text = await resp.text()
                low = text.lower()
                # 挑战/风控页特征（含变体：验证人类/JS 挑战/reCAPTCHA 等）
                if any(k in low for k in ["cf-chl", "cf-challenge", "challenges.cloudflare",
                                          "cf-browser-verification", "attention required",
                                          "just a moment", "verify you are human",
                                          "checking your browser", "enable javascript",
                                          "cf-turnstile", "challenge-platform",
                                          "recaptcha", "hcaptcha", "turnstile"]):
                    return "封锁"
                # 平台自身页面：title 含平台名才算可用（挑战页 title 不含平台名）
                m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
                title = re.sub(r"\s+", " ", m.group(1)).strip().lower() if m else ""
                if name and name.lower() in title:
                    return "可用"
                # 大页面结构兜底：真实业务页（登录墙等）通常远大于挑战页；
                # v4.37.0 收紧：同时排除带挑战关键字的大页面（防 CF 变体页误放行）
                if (len(text) > 15000
                        and any(k in low for k in
                                ["window.__NUXT", "react-root", 'id="root"',
                                 "window.__NEXT_DATA__"])
                        and not any(k in low for k in
                                    ["cf-challenge", "just a moment", "challenge-platform",
                                     "cf-turnstile", "attention required"])):
                    return "可用"
                return "封锁"
            return f"({status})"
    except Exception:
        return "错误(连接失败)"


async def check_bilibili(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Bilibili 可访问性"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with session.get(
            "https://www.bilibili.com",
            proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
        ) as resp:
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception as e:
        return f"错误({type(e).__name__})"


BILI_TW_EP_IDS = [268176, 268177, 268178, 268173]


async def check_bilibili_tw(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 B站港澳台解锁：TW-only 番剧 playurl 是否返回可播放流"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        }
        for ep in BILI_TW_EP_IDS:
            try:
                async with session.get(
                    f"https://api.bilibili.com/pgc/player/web/playurl?ep_id={ep}"
                    "&qn=0&otype=json&fnval=16&fourk=1&module=bangumi",
                    proxy=proxy, headers=headers,
                    # v4.38.0：单 ep 缩短超时（total 8→5、connect 3），4 ep 串行最坏 32s→20s
                    timeout=aiohttp.ClientTimeout(total=5, connect=3),
                ) as resp:
                    # v4.27.0：非 200（412 风控等）归"错误"类 → 触发重试一次，
                    # 旧实现 resp.json() 抛异常被吞 → 瞬时风控被永久判"失败"
                    if resp.status != 200:
                        return f"错误(HTTP {resp.status})"
                    data = await resp.json()
                code = data.get("code", -1)
                msg = str(data.get("message", ""))
                # 按错误码判区域限制（-10403 为官方"区域限制"码；message 匹配仅作兜底）
                if code == -10403:
                    return "失败(区域限制)"
                if "区域" in msg or "版权" in msg or "地区" in msg:
                    return "失败(区域限制)"
                if code == 0:
                    res = data.get("result") or {}
                    if res.get("durl") or res.get("dash"):
                        return "解锁(港澳台)"
            except Exception:
                continue
        return "失败"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_tiktok(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 TikTok 可访问性：从页面提取地区码，区分风控页

    v4.37.0：地区码语义改"可用(XX)"——页面 200 带地区码只证明"服务可达+识别到地区"，
    不证明版权内容解锁（首页对绝大多数地区均返回 200），不再以"解锁"误导
    """
    try:
        async with session.get(
            "https://www.tiktok.com/explore", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            region = ""
            for pat in (r'"region":"([A-Z]{2})"', r'"region":\s*"([A-Z]{2})"',
                        r'"appRegion":"([A-Z]{2})"'):
                m = re.search(pat, text)
                if m:
                    region = m.group(1)
                    break
            if resp.status != 200:
                return f"({resp.status})"
            low = text.lower()
            if ("is-verify" in low or "captcha" in low or "access denied" in low) and not region:
                return "失败(风控)"
            if region:
                return f"可用({region})"
            return "可用"
    except Exception:
        return "错误(连接失败)"


async def check_spotify(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Spotify 可访问性：地区重定向 / 页面 territory 字段

    v4.37.0：地区码语义改"可用(XX)"（服务可达+识别到地区，非版权内容解锁证明）
    """
    try:
        async with session.get(
            "https://www.spotify.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=False,
        ) as resp:
            if resp.status in (301, 302, 307, 308):
                loc = resp.headers.get("Location", "")
                m = re.search(r"spotify\.com/([a-z]{2})(/|$)", loc)
                if m:
                    return f"可用({m.group(1).upper()})"
                # 现代 Spotify 重定向到 open.spotify.com（Location 无国家码），
                # 跟到落地页尝试提取 territory 字段
                if loc and loc.startswith("http"):
                    async with session.get(
                        loc, proxy=proxy, headers=_STREAM_UA,
                        timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                        allow_redirects=True,
                    ) as resp2:
                        text = await resp2.text()
                        m = re.search(r'"territory"\s*:\s*"([A-Z]{2})"', text)
                        if not m:
                            m = re.search(r"data-territory=\"([a-z]{2})\"", text)
                        if m:
                            return f"可用({m.group(1).upper()})"
                        if resp2.status == 200:
                            return "可用"
                        return f"({resp2.status})"
                return "可用"  # 有地区重定向但未携带国家码，视为可访问
            text = await resp.text()
            m = re.search(r'"territory":"([A-Z]{2})"', text)
            if not m:
                m = re.search(r"data-territory=\"([a-z]{2})\"", text)
            if m:
                return f"可用({m.group(1).upper()})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_steam(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Steam 商店可访问性：steamcountry 字段（v4.37.0：地区码语义改"可用(XX)"）"""
    try:
        async with session.get(
            "https://store.steampowered.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            m = re.search(r'"steamcountry"\s*:\s*"([a-z]{2})"', text, re.IGNORECASE)
            if m:
                return f"可用({m.group(1).upper()})"
            # cookie 兜底（实测响应头 cookie 名为 steamCountry，大写 C）
            cc = resp.cookies.get("steamCountry") or resp.cookies.get("steamcountry")
            if cc:
                code = str(cc.value).split("%")[0][:2]
                if code.isalpha():
                    return f"可用({code.upper()})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_primevideo(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Prime Video 可访问性：territory 字段（v4.37.0：地区码语义改"可用(XX)"）"""
    try:
        async with session.get(
            "https://www.primevideo.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            region = ""
            for pat in (r'"currentTerritory"\s*:\s*"([A-Z]{2})"',
                        r'"territory"\s*:\s*"([A-Z]{2})"',
                        r'"TerritoryCode"\s*:\s*"([A-Z]{2})"'):
                m = re.search(pat, text)
                if m:
                    region = m.group(1)
                    break
            if region:
                return f"可用({region})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_max(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Max(HBO) 解锁：可用页 vs 区域不可用页

    v4.37.0：补页面文案校验（与 check_disney 对齐）——URL 未重定向到 not-available
    但页面内嵌区域拦截文案时不再误判；200 但无 countryCode 降为"可用"而非裸"解锁"
    """
    try:
        async with session.get(
            "https://www.max.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            final_url = str(resp.url)
            if "not-available" in final_url or "unavailable" in final_url.lower():
                return "失败(区域不可用)"
            text = await resp.text()
            low = text.lower()
            # 页面文案区域拦截（URL 未重定向时的兜底，与 check_disney 对齐）
            if any(k in low for k in ("not available in your region", "not available in your country",
                                      "unavailable in your region", "choose your region")):
                return "失败(区域不可用)"
            m = re.search(r'"countryCode"\s*:\s*"([A-Z]{2})"', text)
            if resp.status == 200:
                if m:
                    return f"解锁({m.group(1)})"
                return "可用"  # v4.37.0：200 但无地区码 → 仅"可用"，不裸判解锁
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


STREAMING_CHECKERS = {
    "youtube": check_youtube,
    "netflix": check_netflix,
    "disney": check_disney,
    "chatgpt": check_chatgpt,
    "claude": check_claude,        # v4.33.0：api.anthropic.com 区域判别（网页被 CF 风控误杀）
    "perplexity": check_perplexity,  # v4.33.0：api.perplexity.ai 区域判别（同上）
    # v4.38.0：hbomax 复用 check_max（HBO Max 已并入 Max，hbomax.com 重定向 max.com，
    # 消除两列走不同判定路径导致的结果不一致）
    "hbomax": check_max,
    "bilibili": check_bilibili,
    "bilibili_tw": check_bilibili_tw,
    "tiktok": check_tiktok,
    "spotify": check_spotify,
    "steam": check_steam,
    "primevideo": check_primevideo,
    "max": check_max,
}


async def check_one_node_streaming(session: aiohttp.ClientSession, proxy: str,
                                    node: ProxyNode, services: list = None) -> dict:
    """检测单个节点的流媒体（用指定服务列表，默认全部）

    可靠性设计：
    - 瞬时"错误"类结果重试一次（不重试明确的失败/封锁）
    - 死节点早期终止：先测前 3 个服务，全为连接失败 → 其余服务标"跳过"
    """
    if services is None:
        services = FULL_STREAMING_SERVICES

    async def _run_one(svc: dict) -> tuple[str, str]:
        sid = svc["id"]
        if sid in STREAMING_CHECKERS:
            result = await STREAMING_CHECKERS[sid](session, proxy)
        else:
            result = await check_generic(session, proxy, svc["url"], svc["name"])
        return sid, result

    async def _run_batch(batch: list) -> dict:
        """并发跑一批服务：异常/缺失条目统一记为错误(连接失败)"""
        results_list = await asyncio.gather(*[_run_one(s) for s in batch],
                                            return_exceptions=True)
        batch_dict = {}
        for item in results_list:
            # v4.38.0：gather(return_exceptions=True) 下异常对象不是 (k,v) 元组，
            # 由下方缺失 key 兜底补"错误(连接失败)"；元组第 2 元素恒为检测器返回值字符串
            if isinstance(item, tuple) and len(item) == 2:
                k, v = item
                batch_dict[k] = v
        for s in batch:  # 兜底：任何缺失 key 视为连接失败，保证可重试/可判定
            if s["id"] not in batch_dict:
                batch_dict[s["id"]] = "错误(连接失败)"
        return batch_dict

    async def _retry_errors(batch: list, batch_dict: dict) -> dict:
        """对"错误"类结果重试一次"""
        retry_svcs = [s for s in batch
                      if isinstance(batch_dict.get(s["id"]), str)
                      and batch_dict.get(s["id"], "").startswith("错误")]
        if retry_svcs:
            await asyncio.sleep(0.5)
            retry_list = await asyncio.gather(*[_run_one(s) for s in retry_svcs],
                                              return_exceptions=True)
            for item in retry_list:
                if isinstance(item, tuple) and len(item) == 2:
                    k, v = item
                    if not isinstance(v, BaseException):
                        batch_dict[k] = v
        return batch_dict

    if len(services) <= 3:
        return await _retry_errors(services, await _run_batch(services))

    # 死节点预检：前 3 个服务全为连接错误 → 其余服务不再实测
    first_batch = services[:3]
    result_dict = await _retry_errors(first_batch, await _run_batch(first_batch))
    if all(isinstance(v, str) and v.startswith("错误") for v in result_dict.values()):
        for s in services[3:]:
            result_dict[s["id"]] = "跳过(节点不可达)"
        return result_dict
    rest_dict = await _retry_errors(services[3:], await _run_batch(services[3:]))
    result_dict.update(rest_dict)
    return result_dict


def _log_streaming_details(node_name: str, streaming: dict) -> None:
    """JSONL 记录单节点流媒体汇总 + 每平台明细"""
    unlocked = sum(1 for v in streaming.values()
                   if "解锁" in v or "可用" in v or "成功" in v)
    logger.debug(
        "解锁 %s: %d/%d 平台", node_name, unlocked, len(streaming),
        extra=_ev("streaming_done", {"node": node_name, "unlocked": unlocked,
                                     "total": len(streaming)}))
    for sid, val in streaming.items():
        logger.debug(
            "流媒体 %s %s=%s", node_name, sid, val,
            extra=_ev("streaming_result", {"node": node_name, "service": sid, "result": val}))


async def run_streaming_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                              results: dict[str, TestResult],
                              services: list = None) -> None:
    """运行流媒体解锁检测（用指定服务列表）"""
    pbar = tqdm(total=len(nodes), desc="解锁检测", unit="节点", mininterval=1.0, leave=False)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    ssl_ctx = _verified_ssl()  # v4.35.0：默认校验证书（防出口 MITM）
    try:
        for node in nodes:
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 检测中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                if node.name in results and not results[node.name].error:
                    results[node.name].error = "切换失败"  # v4.28.0：如实记录
                pbar.set_postfix_str(f"{display} 切换失败", refresh=False)
                pbar.update(1)
                continue
            await asyncio.sleep(0.3)
            proxy = mihomo.get_proxy_url()
            # 每个节点独立 session，防止连接复用导致走错出口
            async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True),
                    max_field_size=65536, max_line_size=65536) as sess:
                streaming = await check_one_node_streaming(sess, proxy, node, services)
                if node.name in results:
                    results[node.name].streaming = streaming
                # 统计解锁数
                unlocked = sum(1 for v in streaming.values()
                              if "解锁" in v or "可用" in v or "成功" in v)
                _log_streaming_details(node.name, streaming)
                pbar.set_postfix_str(f"{display} {unlocked}/{len(streaming)}", refresh=False)
                pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()

__all__ = ['check_youtube', '_extract_yt_region', 'check_netflix', 'check_disney', 'check_chatgpt', 'check_claude', 'check_perplexity', 'check_generic', 'check_bilibili', 'BILI_TW_EP_IDS', 'check_bilibili_tw', 'check_tiktok', 'check_spotify', 'check_steam', 'check_primevideo', 'check_max', 'STREAMING_CHECKERS', 'check_one_node_streaming', '_log_streaming_details', 'run_streaming_test']
