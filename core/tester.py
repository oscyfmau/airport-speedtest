#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测速执行器：HTTP 速度测试（含兼容重导出：流媒体/IP/网页检测符号）"""
import asyncio
import time
from urllib.parse import urlparse

import aiohttp
from tqdm import tqdm

from . import state
from .config import *
from .engine import *
from .ip_quality import *
from .logging_setup import *
from .models import *
from .streaming import *
from .utils import *
from .webpage import *

async def test_node_speed(mihomo, node: ProxyNode) -> tuple:
    """通过 mihomo 测试节点 HTTP 延迟和下载速度（单节点多连接多源聚合）

    返回 (http_latency, speed, max_speed, per_sec, error_note)

    可靠性设计：
    - DOWNLOAD_CONNS 路并发连接，轮流取 SPEED_TEST_URLS（至少 2 个源）
    - 窗口从首个字节起计时，窗口满即取消其余连接（不等慢连接）
    - 平均速度排除首秒槽（TCP 慢启动剥离），峰值取每秒最大槽
    - 前 SLOW_ABORT_SECONDS 秒累计下载 < SLOW_ABORT_BYTES → 提前终止
    """
    proxy = mihomo.get_proxy_url()
    http_latency = None
    speed = None
    max_speed = None
    per_sec = []   # 确保任何异常路径下都有定义
    error_note = None
    window_secs = state.SPEED_WINDOW_SECONDS
    num_slots = int(window_secs)
    try:
        ssl_ctx = _no_verify_ssl()
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        async with aiohttp.ClientSession(connector=connector) as sess:
            # 先测 HTTP 延迟（失败不阻塞测速）
            try:
                t0 = time.monotonic()
                async with sess.get(
                    "https://www.gstatic.com/generate_204",
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=HTTP_LATENCY_TIMEOUT),
                ) as resp:
                    if resp.status == 204:
                        http_latency = (time.monotonic() - t0) * 1000
            except Exception:
                pass

            # 多连接多源下载（4 连接轮流取源；油管直链解析成功时作为第 4 个源）
            urls = list(SPEED_TEST_URLS)
            if state._YOUTUBE_DL_URL:
                urls.append(state._YOUTUBE_DL_URL)
            slot_bytes = [0] * num_slots
            downloaded = 0
            t_first = None
            aborted_slow = False
            finished = asyncio.Event()

            async def download_one(i: int):
                """单路下载任务：连接 i 取第 i % len(urls) 个源"""
                nonlocal downloaded, t_first, aborted_slow
                url = urls[i % len(urls)]
                got = 0
                status = None
                try:
                    async with sess.get(
                        url,
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=HTTP_DOWNLOAD_TIMEOUT),
                    ) as resp:
                        status = resp.status
                        if resp.status != 200:
                            return
                        async for chunk in resp.content.iter_chunked(65536):
                            if finished.is_set():
                                return
                            if t_first is None:
                                t_first = time.monotonic()
                            elapsed = time.monotonic() - t_first
                            if elapsed >= window_secs:
                                finished.set()  # 窗口已满
                                return
                            idx = max(0, min(int(elapsed), num_slots - 1))
                            slot_bytes[idx] += len(chunk)
                            downloaded += len(chunk)
                            state._RUN_BYTES += len(chunk)
                            got += len(chunk)
                            # 慢节点提前终止
                            if elapsed >= SLOW_ABORT_SECONDS and downloaded < SLOW_ABORT_BYTES:
                                aborted_slow = True
                                logger.debug(
                                    "慢节点提前终止: %s", node.name,
                                    extra=_ev("speed_abort_slow",
                                              {"node": node.name, "downloaded_bytes": downloaded}))
                                finished.set()
                                return
                except Exception as e:
                    logger.debug("test_node_speed conn %d failed for %s: %s", i, node.name,
                                 _safe_exc_str(e),
                                 extra=_ev("speed_conn_error",
                                           {"node": node.name, "conn": i,
                                            "error": _safe_exc_str(e)[:200]}))
                finally:
                    host = urlparse(url).netloc
                    logger.debug(
                        "测速 conn%d 源=%s 状态=%s 下载=%d 字节", i, host, status, got,
                        extra=_ev("speed_conn", {
                            "node": node.name, "conn": i, "source": host,
                            "status": status, "bytes": got}))

            tasks = [asyncio.ensure_future(download_one(i)) for i in range(DOWNLOAD_CONNS)]
            all_done = asyncio.gather(*tasks, return_exceptions=True)
            window_waiter = asyncio.ensure_future(finished.wait())
            try:
                await asyncio.wait_for(
                    asyncio.wait([all_done, window_waiter], return_when=asyncio.FIRST_COMPLETED),
                    timeout=HTTP_DOWNLOAD_TIMEOUT,
                )
            except asyncio.TimeoutError:
                pass
            if not all_done.done():
                # 窗口已满/超时但仍有连接在跑 → 取消并收割（带超时保险）
                for t in tasks:
                    t.cancel()
                try:
                    await asyncio.wait_for(all_done, timeout=5)
                except asyncio.TimeoutError:
                    pass
            if not window_waiter.done():
                window_waiter.cancel()

            # 结果统计
            window_time = min(time.monotonic() - t_first, window_secs) if t_first is not None else 0.0
            if aborted_slow:
                error_note = "速度过低"
            elif downloaded >= MIN_SPEED_BYTES and window_time > 0:
                # 每秒速度：完整秒槽按 1s 折算，末个不满 1 秒的槽按实际秒数折算
                per_sec = []
                full_slots = int(window_time)
                for i in range(num_slots):
                    b = slot_bytes[i]
                    if i < full_slots:
                        per_sec.append((b / 1.0) / (1024 * 1024))
                    elif i == full_slots:
                        frac = window_time - full_slots
                        if frac < 0.25:
                            frac = 0.25  # 下限：避免极短末槽瞬时突发把峰值放大数倍
                        per_sec.append((b / frac) / (1024 * 1024))
                    else:
                        per_sec.append(0.0)
                max_speed = max(per_sec) if per_sec else speed
                # 平均速度：排除首秒慢启动（窗口≥2s 时按 窗口-1s 折算）
                if window_time >= 2.0 and full_slots >= 2:
                    speed = ((downloaded - slot_bytes[0]) / (window_time - 1.0)) / (1024 * 1024)
                else:
                    speed = (downloaded / window_time) / (1024 * 1024)
            else:
                error_note = "下载失败"  # 数据量不足（连接失败/拦截页）
    except Exception as e:
        logger.debug("test_node_speed stats failed for %s: %s", node.name, _safe_exc_str(e))
    return http_latency, speed, max_speed, per_sec, error_note


# _pbar_ticker 定义已移至 utils.py（v4.16.0，避免 streaming↔tester 循环导入）；
# 经 `from .utils import *` 注入本模块，`__all__` 保留该名以维持 `from core.tester import _pbar_ticker` 兼容


async def run_speed_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                         results: dict[str, TestResult]) -> None:
    """运行 HTTP 速度测试（串行：单节点单时刻，节点内部多连接）"""
    pbar = tqdm(total=len(nodes), desc="HTTP测速", unit="节点", mininterval=1.0, leave=False)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    total_n = len(nodes)
    idx_w = len(str(total_n))
    try:
        for i, node in enumerate(nodes):
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 测速中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                logger.warning("切换节点失败: %s", node.name,
                               extra=_ev("switch_node", {"node": node.name, "ok": False}))
                print(f"[{i + 1:>{idx_w}}/{total_n}] {_pad_right(_trunc_width(display, 26), 26)} 切换失败")
                pbar.set_postfix_str(f"{display} 切换失败", refresh=False)
                pbar.update(1)
                continue
            logger.debug("切换节点: %s", node.name,
                         extra=_ev("switch_node", {"node": node.name, "ok": True}))
            await asyncio.sleep(0.2)
            http_latency, speed, max_speed, per_sec, err_note = await test_node_speed(mihomo, node)
            if node.name in results:
                results[node.name].http_latency = http_latency
                results[node.name].speed = speed
                results[node.name].max_speed = max_speed
                results[node.name].speed_per_sec = per_sec
                if err_note:
                    results[node.name].error = err_note
            logger.debug(
                "测速 %s 延迟=%s 平均=%s 峰值=%s %s",
                node.name,
                f"{http_latency:.0f}ms" if http_latency else "--",
                f"{speed:.1f}MB/s" if speed else "--",
                f"{max_speed:.1f}MB/s" if max_speed else "--",
                err_note or "",
                extra=_ev("speed_done", {
                    "node": node.name,
                    "http_latency_ms": http_latency,
                    "avg_mbs": speed,
                    "max_mbs": max_speed,
                    "error": err_note or None,
                }),
            )
            lat_txt = f"{http_latency:.0f}ms" if http_latency else "--"
            spd_txt = f"{speed:.1f}MB/s" if speed else (err_note or "--")
            # 紧凑结果行（无时间戳）：与 tqdm 并存，用户逐节点可见
            print(f"[{i + 1:>{idx_w}}/{total_n}] {_pad_right(_trunc_width(display, 26), 26)} "
                  f"{lat_txt:>7} {spd_txt:>10}")
            pbar.set_postfix_str(
                f"{display} {lat_txt} {spd_txt}",
                refresh=False,
            )
            pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()

__all__ = ['test_node_speed', '_pbar_ticker', 'run_speed_test']
