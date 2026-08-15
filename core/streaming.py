#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流媒体解锁检测：专用检测器 / 通用检测 / 批量运行"""
import asyncio
import re

import aiohttp
from tqdm import tqdm

from .config import *
from .engine import *
from .logging_setup import *
from .models import *
from .utils import *

async def check_youtube(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 YouTube Premium 解锁，如果 Premium 送中则回退到普通 YouTube"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,en;q=0.9",
        }
        async with session.get(
            "https://www.youtube.com/premium", proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
        ) as resp:
            text = await resp.text()
            # 送中检测
            if "www.google.cn" in text:
                # 回退检测普通 YouTube 是否可访问
                try:
                    async with session.get("https://www.youtube.com", proxy=proxy,
                        headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r2:
                        if r2.status == 200:
                            return "可用(CN)"
                except Exception:
                    pass
                return "送中(CN)"
            # 区域不可用
            if "Premium is not available in your country" in text:
                return "失败(区域限制)"
            # 提取地区
            region = ""
            m = re.search(r'"countryCode":"([A-Z]{2})"', text)
            if m:
                region = m.group(1)
            if not region:
                m = re.search(r'"INNERTUBE_CONTEXT_GL"\s*:\s*"([A-Z]{2})"', text)
                if m:
                    region = m.group(1)
            # ad-free 标识=解锁
            if "ad-free" in text or "YouTube and YouTube Music ad-free" in text:
                if region:
                    return f"解锁({region})"
                return "解锁(未知)"
            # 有地区代码但无 ad-free → 无 Premium 解锁但 YouTube 可访问
            if region:
                return f"可用({region})"
            return "失败(无Premium标识)"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_netflix(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Netflix 解锁（参考 RegionRestrictionCheck）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async def _check(url: str) -> str:
            try:
                async with session.get(url, proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                ) as r:
                    if r.status != 200:
                        return "blocked"
                    t = await r.text()
                    if "Not Available" in t or "not available" in t:
                        return "blocked"
                    region = ""
                    m = re.search(r'"country"\s*:\s*"([A-Z]{2})"', t)
                    if m:
                        region = m.group(1)
                    return f"ok:{region}" if region else "ok"
            except Exception:
                return "错误(连接失败)"  # 连接类异常与业务封锁区分，供死节点预检判定

        r1 = await _check("https://www.netflix.com/title/81280792")  # 自制剧
        r2 = await _check("https://www.netflix.com/title/70143836")  # 非自制剧

        if r1.startswith("错误") or r2.startswith("错误"):
            return "错误(连接失败)"
        if r1.startswith("ok") and r2.startswith("ok"):
            region = r1.split(":")[1] if ":" in r1 else r2.split(":")[1] if ":" in r2 else ""
            return f"解锁({region})" if region else "解锁"
        elif r1.startswith("ok") and not r2.startswith("ok"):
            return "仅自制剧"
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
    """检测 ChatGPT（多端点探测）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        async def _probe(url: str) -> tuple[int, str]:
            """探测一个端点，返回 (status, text)"""
            try:
                async with session.get(url, proxy=proxy, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=8),
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

        # 试 cdn-cgi/trace 提取地区
        _, trace = await _probe("https://chat.openai.com/cdn-cgi/trace")
        region = ""
        for line in trace.splitlines():
            if line.startswith("loc="):
                region = line[4:].strip()
                break

        # favicon 403 + trace 有地区 → CF 拦截了路径但能通
        if status2 == 403 and region:
            return f"解锁({region})"
        # trace 有地区 → 能通
        if region:
            return f"解锁({region})"
        # 全部失败
        if status2 == 403:
            return "封锁"
        return "错误(连接失败)"
    except Exception as e:
        return f"错误({type(e).__name__})"


async def check_generic(session: aiohttp.ClientSession, proxy: str, url: str, name: str) -> str:
    """通用检测（跟进重定向，允许 3xx 也算可用）"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with session.get(
            url, proxy=proxy, headers=headers,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            status = resp.status
            # 有些服务返回 3xx/404 但也算可访问（如某些仅登录后可见的平台）
            if status in (200, 201, 202, 204, 301, 302, 303, 307, 308):
                return "可用"
            # 403：Cloudflare/风控拦截页一律判封锁；仅当页面呈现正常业务结构（如登录墙）才算可用
            if status == 403:
                text = await resp.text()
                if any(kw in text for kw in ["cf-chl", "cf-challenge", "challenges.cloudflare",
                                             "cf-browser-verification", "Attention Required",
                                             "Just a moment"]):
                    return "封锁"
                if any(kw in text for kw in ["<html", "<!DOCTYPE", "window.__NUXT",
                                             "react-root"]):
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
                    timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                ) as resp:
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
    """检测 TikTok 解锁：从页面提取地区码，区分风控页"""
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
                return f"解锁({region})"
            return "可用"
    except Exception:
        return "错误(连接失败)"


async def check_spotify(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Spotify 解锁：地区重定向 / 页面 territory 字段"""
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
                    return f"解锁({m.group(1).upper()})"
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
                            return f"解锁({m.group(1).upper()})"
                        if resp2.status == 200:
                            return "可用"
                        return f"({resp2.status})"
                return "可用"  # 有地区重定向但未携带国家码，视为可访问
            text = await resp.text()
            m = re.search(r'"territory":"([A-Z]{2})"', text)
            if not m:
                m = re.search(r"data-territory=\"([a-z]{2})\"", text)
            if m:
                return f"解锁({m.group(1).upper()})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_steam(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Steam 商店解锁：steamcountry 字段"""
    try:
        async with session.get(
            "https://store.steampowered.com/", proxy=proxy, headers=_STREAM_UA,
            timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
            allow_redirects=True,
        ) as resp:
            text = await resp.text()
            m = re.search(r'"steamcountry"\s*:\s*"([a-z]{2})"', text, re.IGNORECASE)
            if m:
                return f"解锁({m.group(1).upper()})"
            # cookie 兜底（实测响应头 cookie 名为 steamCountry，大写 C）
            cc = resp.cookies.get("steamCountry") or resp.cookies.get("steamcountry")
            if cc:
                code = str(cc.value).split("%")[0][:2]
                if code.isalpha():
                    return f"解锁({code.upper()})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_primevideo(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Prime Video 解锁：territory 字段"""
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
                return f"解锁({region})"
            if resp.status == 200:
                return "可用"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


async def check_max(session: aiohttp.ClientSession, proxy: str) -> str:
    """检测 Max(HBO) 解锁：可用页 vs 区域不可用页"""
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
            m = re.search(r'"countryCode"\s*:\s*"([A-Z]{2})"', text)
            if resp.status == 200:
                return f"解锁({m.group(1)})" if m else "解锁"
            return f"({resp.status})"
    except Exception:
        return "错误(连接失败)"


STREAMING_CHECKERS = {
    "youtube": check_youtube,
    "netflix": check_netflix,
    "disney": check_disney,
    "chatgpt": check_chatgpt,
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
            if isinstance(item, tuple) and len(item) == 2:
                k, v = item
                batch_dict[k] = "错误(连接失败)" if isinstance(v, BaseException) else v
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
    pbar = tqdm(total=len(nodes), desc="解锁检测", unit="节点", mininterval=1.0)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    ssl_ctx = _no_verify_ssl()
    try:
        for node in nodes:
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 检测中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                pbar.set_postfix_str(f"{display} 切换失败", refresh=False)
                pbar.update(1)
                continue
            await asyncio.sleep(0.3)
            proxy = mihomo.get_proxy_url()
            # 每个节点独立 session，防止连接复用导致走错出口
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
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

__all__ = ['check_youtube', 'check_netflix', 'check_disney', 'check_chatgpt', 'check_generic', 'check_bilibili', 'BILI_TW_EP_IDS', 'check_bilibili_tw', 'check_tiktok', 'check_spotify', 'check_steam', 'check_primevideo', 'check_max', 'STREAMING_CHECKERS', 'check_one_node_streaming', '_log_streaming_details', 'run_streaming_test']
