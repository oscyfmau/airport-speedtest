#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页模拟测速（落地 CN 自动换国内站点）"""
import asyncio
import time

import aiohttp
from tqdm import tqdm

from .config import *
from .engine import *
from .logging_setup import *
from .models import *
from .utils import *

async def check_one_node_webpage(session: aiohttp.ClientSession, proxy: str,
                                 ip_info: dict, node_name: str = "") -> dict:
    """网页模拟测速：并发 GET 站点列表，返回 {站点: 耗时ms（失败=-1）, avg_ms}

    ip_info 为当前节点 IP 质量结果，落地为 CN 时自动换国内站点（百度/哔哩哔哩/腾讯）。
    """
    urls = WPS_CN_URLS if (ip_info or {}).get("country") == "CN" else WPS_INTERNATIONAL_URLS
    results: dict = {}

    async def one(site: str, url: str) -> None:
        t0 = time.monotonic()
        try:
            async with session.get(
                url, proxy=proxy, headers=_STREAM_UA,
                timeout=aiohttp.ClientTimeout(total=STREAMING_TEST_TIMEOUT),
                allow_redirects=True,
            ) as resp:
                elapsed = (time.monotonic() - t0) * 1000
                results[site] = round(elapsed) if resp.status < 400 else -1
                await resp.release()
        except Exception:
            results[site] = -1

    await asyncio.gather(*[one(s, u) for s, u in urls])
    ok_vals = [v for v in results.values() if v > 0]
    results["avg_ms"] = round(sum(ok_vals) / len(ok_vals)) if ok_vals else -1
    logger.debug(
        "网页模拟 %s: 均耗 %s ms (%s)", node_name or "-", results["avg_ms"],
        {k: v for k, v in results.items() if k != "avg_ms"},
        extra=_ev("webpage_done", {"node": node_name or "-", "avg_ms": results["avg_ms"],
                                   "sites": {k: v for k, v in results.items() if k != "avg_ms"}}))
    return results


async def run_webpage_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                           results: dict[str, TestResult]) -> None:
    """运行网页模拟测速（串行路径，与 run_ip_quality_test 同构）"""
    pbar = tqdm(total=len(nodes), desc="网页模拟", unit="节点", mininterval=1.0)
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
            await asyncio.sleep(0.5)  # 给切换和 DNS 留时间
            proxy = mihomo.get_proxy_url()
            async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as session:
                ip_info = (results.get(node.name).ip_info
                           if node.name in results else {}) or {}
                web = await check_one_node_webpage(session, proxy, ip_info, node.name)
                if node.name in results:
                    results[node.name].webpage = web
                pbar.set_postfix_str(
                    f"{display} {web.get('avg_ms', '?')}ms", refresh=False)
                pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()

__all__ = ['check_one_node_webpage', 'run_webpage_test']
