#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试流程编排：run_test / 节点并行流水线 / 提前结束路径"""
import asyncio
import os
import sys
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
from .parser import *
from .profiles import append_run, cleanup_outputs  # v4.29.0 归档 / v4.31.0 产物清理
from .report import *
from .settings import load_settings  # v4.29.0：大流量确认开关
from .streaming import *
from .tester import *
from .utils import *
from .webpage import *

def _finish_partial(results_dict: dict, mode: str, display_mode: str,
                    t_start: float, sort_by: str, reason: str = "interrupted") -> str:
    """提前结束路径共用：生成 PNG + JSON 并记录路径

    v4.36.0：reason 由调用点传入（此前一律硬编码 "interrupted"，与
    "无可达节点/mihomo 缺失" 等提前结束场景不符）
    """
    logger.warning(
        "提前结束，生成部分报告",
        extra=_ev("run_end", {"completed": False, "partial": True, "reason": reason,
                              "nodes": len(results_dict)}))
    _mark_reuse(list(results_dict.values()))  # 复用检测四档（无 IP 数据时空转）
    report_ts = _new_report_timestamp()  # v4.29.0：PNG/JSON 共享时间戳（毫秒防同秒覆盖）
    run_bytes = int(state._RUN_BYTES)
    img_path = ""
    try:
        img_path = generate_report_image(
            list(results_dict.values()), mode, time.monotonic() - t_start, sort_by,
            display_mode=display_mode, report_ts=report_ts, run_bytes=run_bytes,
        )
    except Exception:
        logger.exception("报告图片生成失败，仅导出 JSON 数据")
    try:
        json_path = export_results_json(list(results_dict.values()), mode,
                                        display_mode=display_mode,
                                        report_ts=report_ts, run_bytes=run_bytes)
    except Exception as e:
        logger.warning("JSON 导出失败: %s", _safe_exc_str(e))
        json_path = ""
    append_run(list(results_dict.values()), mode, display_mode, report_ts, json_path)  # v4.29.0：节点档案归档
    try:
        # v4.31.0：测后产物自动清理（静默执行，异常不影响报告）
        st = load_settings()
        cl = cleanup_outputs(st.get("keep_reports", KEEP_REPORTS_DEFAULT),
                             st.get("keep_logs_days", KEEP_LOGS_DAYS_DEFAULT))
        if cl["reports_deleted"] or cl["logs_deleted"]:
            logger.info("产物清理: 报告 -%d 份、日志 -%d 个",
                        cl["reports_deleted"], cl["logs_deleted"],
                        extra=_ev("profiles_cleanup", cl))
    except Exception:
        pass
    if img_path:
        logger.info(f"报告已生成: {img_path}")
    if json_path:
        logger.info(f"数据已生成: {json_path}")
    try:
        print_console_summary(list(results_dict.values()), sort_by)
    except Exception:
        pass  # 控制台小结失败不影响报告
    return img_path


async def _run_node_pipeline(pool: MihomoWorkerPool, node_tasks: list,
                             results_dict: dict, streaming_services: list) -> None:
    """并行流水线：pool 槽位即并发度，每个节点依次完成 流媒体→IP 后释放槽位
    （测速恒串行，不在此流水线内）"""
    queue: asyncio.Queue = asyncio.Queue()
    for t in node_tasks:
        await queue.put(t)
    for _ in pool.workers:
        await queue.put(None)  # 终止哨兵

    ssl_ctx = _verified_ssl()  # v4.35.0：默认校验证书（防出口 MITM）
    ip_lock = asyncio.Lock()
    seen_ips: set = set()
    last_ip_check = [0.0]  # 全局节流：免费 IP API 有限额，串行 + 最小间隔防 429

    pbar = tqdm(total=len(node_tasks), desc="节点测试", unit="节点", mininterval=1.0, leave=False)

    async def worker_loop(worker: MihomoWorker):
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            node, do_stream, do_ip, do_web = item
            try:
                pbar.set_postfix_str(f"{_flag_to_text(node.name)} 加载中")
                if not await worker.load_node(node):
                    if node.name in results_dict:
                        results_dict[node.name].error = "节点加载失败"
                    continue
                proxy = worker.get_proxy_url()

                # 1) 流媒体解锁
                if do_stream:
                    await asyncio.sleep(0.3)
                    async with aiohttp.ClientSession(
                            connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True),
                            max_field_size=65536, max_line_size=65536) as sess:
                        streaming = await check_one_node_streaming(sess, proxy, node, streaming_services)
                        if node.name in results_dict:
                            results_dict[node.name].streaming = streaming
                        unlocked = sum(1 for v in streaming.values()
                                       if "解锁" in v or "可用" in v or "成功" in v)
                        _log_streaming_details(node.name, streaming)
                        pbar.set_postfix_str(f"{_flag_to_text(node.name)} 解锁{unlocked}/{len(streaming)}")

                # 2) IP 质量（多源回退 + 全局节流）
                if do_ip:
                    await asyncio.sleep(0.3)
                    # 间隔节流（v4.27.0）：仅簿记上锁，网络请求不持锁——
                    # 坏节点最长 4源×2次×10s ≈ 80s 超时不再阻塞其余 worker
                    async with ip_lock:
                        wait = IP_CHECK_INTERVAL - (time.monotonic() - last_ip_check[0])
                        if wait > 0:
                            await asyncio.sleep(wait)
                        last_ip_check[0] = time.monotonic()
                    async with aiohttp.ClientSession(
                            connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
                        ip_info = await check_ip_quality(sess, proxy)
                    if node.name in results_dict:
                        results_dict[node.name].ip_info = ip_info
                        curr_ip = ip_info.get("ip", "")
                        if curr_ip:
                            if curr_ip in seen_ips:
                                results_dict[node.name].ip_info["same_ip_warning"] = True
                            seen_ips.add(curr_ip)
                    risk = ip_info.get("risk_score")
                    risk = "?" if risk is None else risk
                    _log_ip_details(node.name, ip_info)
                    pbar.set_postfix_str(f"{_flag_to_text(node.name)} 风险:{risk}%")

                # 3) 网页模拟测速（依赖 IP 归属选站点；无 IP 数据时用国际站点）
                if do_web:
                    await asyncio.sleep(0.3)
                    async with aiohttp.ClientSession(
                            connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True),
                            max_field_size=65536, max_line_size=65536) as sess:
                        ip_info = (results_dict.get(node.name).ip_info
                                   if node.name in results_dict else {}) or {}
                        web = await check_one_node_webpage(sess, proxy, ip_info, node.name)
                        if node.name in results_dict:
                            results_dict[node.name].webpage = web
                        pbar.set_postfix_str(
                            f"{_flag_to_text(node.name)} 网页{web.get('avg_ms', '?')}ms")
            except Exception as e:
                if node.name in results_dict:
                    results_dict[node.name].error = _safe_exc_str(e)
                logger.debug("节点 %s 流水线异常: %s", node.name, _safe_exc_str(e))
            finally:
                queue.task_done()
                pbar.update(1)

    try:
        await asyncio.gather(*[worker_loop(w) for w in pool.workers])
    finally:
        pbar.close()


async def _quick_one_node(sess: aiohttp.ClientSession, proxy: str, node: ProxyNode,
                          results_dict: dict) -> None:
    """quick 单节点一条龙：快速测速 + 4 核心流媒体（worker 并行与串行回退共用）"""
    http_latency, speed, max_speed, per_sec, err = await test_node_quick(sess, proxy, node)
    if node.name in results_dict:
        r = results_dict[node.name]
        r.http_latency = http_latency
        r.speed = speed
        r.max_speed = max_speed
        r.speed_per_sec = per_sec
        if err and not r.error:
            r.error = err
    streaming = await check_one_node_streaming(sess, proxy, node, QUICK_STREAMING)
    if node.name in results_dict:
        results_dict[node.name].streaming = streaming
    _log_streaming_details(node.name, streaming)
    logger.debug(
        "快速测速 %s 延迟=%s 平均=%s 峰值=%s %s",
        node.name,
        f"{http_latency:.0f}ms" if http_latency else "--",
        f"{speed:.1f}MB/s" if speed else "--",
        f"{max_speed:.1f}MB/s" if max_speed else "--",
        err or "",
        extra=_ev("speed_done", {
            "node": node.name,
            "http_latency_ms": http_latency,
            "avg_mbs": speed,
            "max_mbs": max_speed,
            "error": err or None,
        }))


async def _run_quick_pipeline(pool: MihomoWorkerPool, nodes: list[ProxyNode],
                              results_dict: dict) -> None:
    """quick 并行一条龙：worker 依次 加载节点 → 快速测速 + 4 核心流媒体"""
    queue: asyncio.Queue = asyncio.Queue()
    for n in nodes:
        await queue.put(n)
    for _ in pool.workers:
        await queue.put(None)  # 终止哨兵
    ssl_ctx = _verified_ssl()  # v4.35.0：默认校验证书（防出口 MITM）
    pbar = tqdm(total=len(nodes), desc="快速检测", unit="节点", mininterval=1.0, leave=False)

    async def worker_loop(worker: MihomoWorker):
        while True:
            node = await queue.get()
            if node is None:
                queue.task_done()
                return
            try:
                pbar.set_postfix_str(f"{_flag_to_text(node.name)} 检测中")
                if not await worker.load_node(node):
                    if node.name in results_dict and not results_dict[node.name].error:
                        results_dict[node.name].error = "节点加载失败"
                    continue
                proxy = worker.get_proxy_url()
                async with aiohttp.ClientSession(
                        connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True),
                        max_field_size=65536, max_line_size=65536) as sess:
                    await _quick_one_node(sess, proxy, node, results_dict)
                    unlocked = sum(1 for v in results_dict[node.name].streaming.values()
                                   if isinstance(v, str) and ("解锁" in v or "可用" in v))
                    pbar.set_postfix_str(f"{_flag_to_text(node.name)} 解锁{unlocked}/4")
            except Exception as e:
                if node.name in results_dict and not results_dict[node.name].error:
                    results_dict[node.name].error = _safe_exc_str(e)
                logger.debug("quick 节点 %s 异常: %s", node.name, _safe_exc_str(e))
            finally:
                queue.task_done()
                pbar.update(1)

    try:
        await asyncio.gather(*[worker_loop(w) for w in pool.workers])
    finally:
        pbar.close()


async def _run_quick_serial(mihomo: MihomoEngine, nodes: list[ProxyNode],
                            results_dict: dict) -> None:
    """quick 串行回退：主引擎 switch_proxy 逐节点（池不可用时）"""
    ssl_ctx = _verified_ssl()  # v4.35.0：默认校验证书（防出口 MITM）
    pbar = tqdm(total=len(nodes), desc="快速检测", unit="节点", mininterval=1.0, leave=False)
    try:
        for node in nodes:
            display = _flag_to_text(node.name)
            pbar.set_postfix_str(f"{display} 检测中...")
            ok = await mihomo.switch_proxy(node.name)
            if not ok:
                if node.name in results_dict and not results_dict[node.name].error:
                    results_dict[node.name].error = "切换失败"
                pbar.update(1)
                continue
            await asyncio.sleep(0.2)
            proxy = mihomo.get_proxy_url()
            async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True),
                    max_field_size=65536, max_line_size=65536) as sess:
                await _quick_one_node(sess, proxy, node, results_dict)
            pbar.update(1)
    finally:
        pbar.close()


async def run_test(subscribe_url, mode: str = "basic", sort_by: str = "default",
                   fast: bool = False, workers: int = DEFAULT_WORKERS,
                   node_filter: str = "", node_limit: int = 0,
                   window_seconds: int = 0) -> str:
    """运行完整测试流程（subscribe_url 支持单个 URL 或 URL 列表）

    node_filter: 节点名关键字过滤（空格/逗号分隔=任一匹配，空串=不过滤）
    node_limit: 只测订阅顺序中的前 N 个节点（0=不限）
    window_seconds: 非 fast 模式下的测速窗口秒数（0=用默认 8s；fast 恒为 5s）
    """
    state.reset_run_state()  # 每次运行重置运行时全局（菜单连续运行防串味）
    t_start = time.monotonic()
    output_mode = mode  # 保留原始模式名（streaming_ai/streaming_all），供文件名/报告头/JSON
    workers = max(1, min(int(workers), MAX_WORKERS))  # 钳制并行度，防异常入参开过多 mihomo 进程
    phase = "初始化"  # 当前阶段（中断事件记录用）
    logger.info(
        "运行开始: 模式=%s workers=%s fast=%s",
        output_mode, workers, fast,
        extra=_ev("run_start", {
            "version": VERSION,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "argv": [_mask_url(a) if a.startswith(("http://", "https://")) else a
                     for a in sys.argv],
            "mode": output_mode,
            "workers": workers,
            "fast": fast,
            "node_filter": node_filter or None,
            "node_limit": node_limit or None,
            "deps": {
                "aiohttp": _pkg_version("aiohttp"),
                "yaml": _pkg_version("PyYAML"),
                "PIL": _pkg_version("Pillow"),
                "tqdm": _pkg_version("tqdm"),
                "requests": _pkg_version("requests"),
                "cloudscraper": HAS_CLOUDSCRAPER,
                "yt_dlp": HAS_YTDLP,
            },
        }),
    )

    # v4.28.0：本机系统代理状态提示（工具内部请求已强制直连，数据不受开关影响；
    # TUN 模式会接管直连 TCP，属用户层不可绕过的例外，明确告知）
    sys_proxy = _system_proxy_info()
    if sys_proxy:
        logger.info(
            "检测到本机系统代理已开启（%s）：本工具内部请求已强制直连、不受其影响；"
            "若本机代理为 TUN 模式，直连 TCP Ping 结果可能被其接管", sys_proxy)

    # Step 1: 解析订阅
    if isinstance(subscribe_url, (list, tuple)):
        urls = [u for u in subscribe_url if u]
        if not urls:
            logger.error("订阅 URL 列表为空",
                         extra=_ev("run_end", {"completed": False, "reason": "empty_urls",
                                               "nodes": 0}))
            return ""
    else:
        urls = [subscribe_url]
    logger.info("=" * 50)
    logger.info("解析订阅: %s", " | ".join(_mask_url(u) for u in urls))
    logger.info("=" * 50)
    try:
        if len(urls) > 1:
            nodes = parse_subscription_urls(urls)
        else:
            nodes = parse_subscription_url(urls[0])
            for n in nodes:
                n.sub_index = 0  # v4.31.0：单订阅打 0（分组对比提示"只有 1 个订阅"）
    except Exception as e:
        logger.error("订阅解析失败: %s", _safe_exc_str(e),
                     extra=_ev("run_end", {"completed": False, "reason": "parse_error",
                                           "nodes": 0,
                                           "error": _safe_exc_str(e)[:200]}))
        return ""

    if not nodes:
        logger.error("未解析到任何节点",
                     extra=_ev("run_end", {"completed": False, "reason": "no_nodes", "nodes": 0}))
        logger.error("  - 可能原因：订阅链接无效、已过期、或仅包含信息节点(127.0.0.1)")
        logger.error("  - 请检查 代理.txt 中的订阅链接是否正确")
        return ""

    # 节点筛选：关键字（任一匹配）+ 前 N 个（订阅顺序）
    if node_filter or node_limit:
        orig_n = len(nodes)
        kws = [k.strip() for k in node_filter.replace(",", " ").split() if k.strip()]
        if kws:
            nodes = [n for n in nodes
                     if any(k.lower() in n.name.lower() for k in kws)]
        if node_limit and len(nodes) > node_limit:
            nodes = nodes[:node_limit]
        if not nodes:
            logger.error("筛选后无匹配节点（关键字=%s 上限=%s）",
                         node_filter or "-", node_limit or "-",
                         extra=_ev("run_end", {"completed": False, "reason": "no_nodes_filtered",
                                               "nodes": 0, "node_filter": node_filter,
                                               "node_limit": node_limit}))
            return ""
        logger.info("节点筛选: %d → %d 个%s", orig_n, len(nodes),
                    f"（关键字: {node_filter}）" if node_filter else f"（前 {node_limit} 个）")

    # v4.29.0：测前流量预估（仅测速类模式；流媒体-only 不下载大流量）
    if mode not in ("streaming", "streaming_ai", "streaming_all"):
        est_lo = _fmt_size(len(nodes) * 10 * 1024 * 1024)
        est_hi = _fmt_size(len(nodes) * 30 * 1024 * 1024)
        print(f"预计下载约 {est_lo}-{est_hi}（{len(nodes)} 节点）")
        if len(nodes) > 50 and load_settings().get("confirm_large_run", True):
            try:
                input("节点较多，回车继续 / Ctrl+C 取消: ")
            except KeyboardInterrupt:
                logger.warning("用户取消大流量测试", extra=_ev("run_end",
                             {"completed": False, "reason": "cancelled_large_run", "nodes": len(nodes)}))
                return ""
            except EOFError:
                pass  # 管道输入：无交互，直接继续

    type_counts = {}
    for n in nodes:
        type_counts[n.type] = type_counts.get(n.type, 0) + 1
    logger.info(
        "[成功] 解析到 %d 个节点", len(nodes),
        extra=_ev("parse_done", {"total": len(nodes), "type_counts": type_counts}),
    )
    for n in nodes[:5]:
        addr = f"{n.type}://{n.server}:{n.port}"
        logger.info(f"   - {_pad_right(n.name, 32)} {addr:>38}")
    if len(nodes) > 5:
        logger.info(f"   ... 还有 {len(nodes) - 5} 个节点")

    # 初始化结果
    results_dict: dict[str, TestResult] = {}
    for n in nodes:
        results_dict[n.name] = TestResult(node=n)

    # 模式别名
    streaming_services = None
    if mode == "speed":
        mode = "basic"
    elif mode == "normal":
        mode = "full"
        streaming_services = COMMON_STREAMING_SERVICES
    elif mode == "streaming_ai":
        mode = "streaming"
        streaming_services = AI_STREAMING_SERVICES
    elif mode == "streaming_all":
        mode = "streaming"

    # --fast：缩短测速窗口（默认 8s → 5s）；非 fast 时可经 window_seconds 参数覆盖（菜单设置）
    if fast:
        state.SPEED_WINDOW_SECONDS = SPEED_WINDOW_FAST_SECONDS
    else:
        try:
            state.SPEED_WINDOW_SECONDS = (max(3, min(int(window_seconds), 30))
                                          if window_seconds > 0 else SPEED_WINDOW_DEFAULT_SECONDS)
        except (TypeError, ValueError):
            state.SPEED_WINDOW_SECONDS = SPEED_WINDOW_DEFAULT_SECONDS  # 非法入参回退默认

    # 计算步骤数
    steps = []
    if mode != "streaming":
        steps.append("TCP检测")
        steps.append("HTTP测速")
    if mode != "basic":
        steps.append("流媒体/IP/网页检测" if mode == "full" else "流媒体检测")
    step_idx = 1

    # 阶段1: TCP 检测（来源A 直连 + 来源B mihomo 隧道并发探测）
    tcp_results = {}
    probe_results = {}
    probe_ok = 0
    success_tcp = 0
    mihomo = MihomoEngine()  # 提前创建：隧道探测与测速阶段共用内核
    pool = None
    used_pool = False
    interrupted = False  # v4.36.0：用户中断标记（中断路径的 run_end 记 completed=False）
    try:
        if mode == "quick":
            # v4.30.0 快速检测：TCP 1 次重试筛活 → 死节点如实标注 → 并行一条龙 → 回退串行
            phase = "快速检测"
            logger.info("=" * 50)
            logger.info(f"[{step_idx}/{len(steps)}] 快速检测（并行 {QUICK_WORKERS} 路近似测速 + 4 核心流媒体）")
            logger.info("=" * 50)
            tcp_results = await run_tcp_ping(nodes, attempts=1, timeouts=(QUICK_TCP_TIMEOUT,))
            for n in nodes:
                latency, ok = tcp_results.get(n.name, (None, 0))
                if n.name in results_dict:
                    results_dict[n.name].tcp_ping = latency
                    if not is_udp_node(n):
                        results_dict[n.name].tcp_loss = 1 - ok
            # 死节点：非 UDP 且直连失败（quick 无隧道探测；UDP 节点无法判定，不判死进流水线实测）
            quick_dead = {n.name for n in nodes
                          if not is_udp_node(n)
                          and (tcp_results.get(n.name) or (None, 0))[0] is None}
            if quick_dead:
                for name in quick_dead:
                    r = results_dict[name]
                    if not r.error:
                        r.error = "节点不可达"
                    r.streaming = {svc["id"]: "跳过(节点不可达)" for svc in QUICK_STREAMING}
                logger.info(
                    "不可达节点 %d 个：已标注「节点不可达」，跳过检测",
                    len(quick_dead),
                    extra=_ev("dead_nodes_skipped", {"count": len(quick_dead),
                                                     "nodes": sorted(quick_dead)}))
            quick_alive = [n for n in nodes if n.name not in quick_dead]
            if not quick_alive:
                logger.error("无可用的节点，跳过后续测试")
                return _finish_partial(results_dict, mode, output_mode, t_start, sort_by,
                                       reason="no_reachable_nodes")
            if not (mihomo.binary_path and os.path.isfile(mihomo.binary_path)):
                logger.error("mihomo 不可用，跳过快速检测")
                return _finish_partial(results_dict, mode, output_mode, t_start, sort_by,
                                       reason="mihomo_missing")
            if QUICK_WORKERS > 1:
                pool = MihomoWorkerPool(mihomo.binary_path, QUICK_WORKERS)
                if await pool.start():
                    used_pool = True
                    logger.info(
                        f"mihomo 并行池就绪: {len(pool.workers)} workers（快速检测）",
                        extra=_ev("worker_pool_start", {"workers": len(pool.workers)}))
                    await _run_quick_pipeline(pool, quick_alive, results_dict)
                else:
                    logger.warning("并行池不可用，回退串行模式")
            if not used_pool:
                mihomo.generate_config(quick_alive)
                await mihomo.start()
                logger.info("mihomo 启动成功",
                            extra=_ev("mihomo_start", {"api_port": mihomo.api_port,
                                                       "mixed_port": mihomo.mixed_port}))
                await _run_quick_serial(mihomo, quick_alive, results_dict)
            step_idx += 1

        if mode not in ("streaming", "quick"):
            phase = "TCP检测"
            logger.info("=" * 50)
            logger.info(f"[{step_idx}/{len(steps)}] TCP Ping 延迟测试")
            logger.info("=" * 50)
            tcp_results = await run_tcp_ping(nodes)
            for n in nodes:
                latency, ok = tcp_results.get(n.name, (None, 0))
                if n.name in results_dict:
                    results_dict[n.name].tcp_ping = latency
                    if not is_udp_node(n):
                        results_dict[n.name].tcp_loss = 3 - ok
            success_tcp = sum(1 for v, _ in tcp_results.values() if v is not None)

            # 来源B：直连超时节点 + UDP 节点 → mihomo 隧道并发探测
            # （v4.27.0 修复：tcp_results 值为 (latency, ok) 元组恒非 None，
            #   旧判断 `is None` 导致 candidates 恒空、隧道探测从未执行）
            candidates = [n for n in nodes if (tcp_results.get(n.name) or (None, 0))[0] is None]
            if candidates and mihomo.binary_path and os.path.isfile(mihomo.binary_path):
                n_conc = min(TCP_PROBE_CONCURRENCY, len(candidates))
                logger.info(f"TCP 直连未通 {len(candidates)} 个，启动 mihomo 隧道探测（并发 {n_conc} 路）...")
                probe_results = await run_tcp_probe_pool(mihomo.binary_path, candidates)
                for name, ok in probe_results.items():
                    if name in results_dict:
                        results_dict[name].tcp_probe = ok
                if probe_results:
                    probe_ok = sum(1 for v in probe_results.values() if v)
                    logger.info(f"隧道探测: {probe_ok}/{len(candidates)} 节点可达")
                else:
                    logger.warning("隧道探测不可用（探测池启动失败），按直连结果继续")

            udp_n = sum(1 for n in nodes if is_udp_node(n))
            extra = f"（UDP节点 {udp_n} 个经隧道探测）" if udp_n else ""
            logger.info(f"TCP 检测完成: 直连 {success_tcp}/{len(nodes)} 可达{extra}")
            step_idx += 1

        # 可达性合并：直连成功 或 隧道探测成功（探测池不可用时 UDP 节点按直连语义保留）
        # （v4.27.0 修复：旧判断 `v is not None` 对元组恒真 → 死节点全部误判可达）
        reachable = {name for name, v in tcp_results.items() if v is not None and v[0] is not None}
        if probe_results:
            reachable |= {name for name, v in probe_results.items() if v}
        else:
            reachable |= {n.name for n in nodes if is_udp_node(n)}
        active_speed = [n for n in nodes if n.name in reachable] if mode != "streaming" else nodes
        active_all = nodes  # 流媒体和 IP 检测用全部节点

        if mode not in ("streaming", "quick") and not active_speed:
            logger.error("无可用的节点，跳过后续测试")
            return _finish_partial(results_dict, mode, output_mode, t_start, sort_by,
                                   reason="no_reachable_nodes")

        if mode != "quick":
            logger.info("启动 mihomo 引擎...")
            logger.info("=" * 50)
            binary_ok = bool(mihomo.binary_path and os.path.isfile(mihomo.binary_path))
            if not binary_ok:
                logger.error("mihomo 不可用，跳过 HTTP 测速及后续测试")
                return _finish_partial(results_dict, mode, output_mode, t_start, sort_by,
                                       reason="mihomo_missing")

        # 阶段2: HTTP 测速（恒串行：单节点单时刻；节点内部 DOWNLOAD_CONNS 路并发连接）
        if mode not in ("streaming", "quick") and active_speed:
            phase = "HTTP测速"
            yt_url = ""
            yt_method = "direct"
            if YOUTUBE_SOURCE_ENABLED:
                # yt-dlp 解析为同步阻塞（网络+子进程），放进 executor 不冻结事件循环
                yt_url = await asyncio.to_thread(resolve_youtube_download_url, 10)
            mihomo.generate_config(active_all)
            await mihomo.start()
            logger.info("mihomo 启动成功",
                        extra=_ev("mihomo_start", {"api_port": mihomo.api_port,
                                                   "mixed_port": mihomo.mixed_port}))
            if YOUTUBE_SOURCE_ENABLED and not yt_url and active_speed:
                # 本机直连失败 → 经首个可达节点隧道再试（节点能访问油管是使用该源的前提）
                ok = await mihomo.switch_proxy(active_speed[0].name)
                if ok:
                    await asyncio.sleep(0.3)
                    yt_url = await asyncio.to_thread(
                        resolve_youtube_download_url, 15, mihomo.get_proxy_url())
                    yt_method = "node_proxy"
            if YOUTUBE_SOURCE_ENABLED:
                if yt_url:
                    logger.info(
                        "油管测速源就绪: %s", urlparse(yt_url).netloc,
                        extra=_ev("yt_source_resolve",
                                  {"method": yt_method, "host": urlparse(yt_url).netloc}))
                else:
                    logger.warning(
                        "油管测速源不可用，使用 %d 个基础源", len(SPEED_TEST_URLS),
                        extra=_ev("yt_source_resolve", {"method": yt_method, "host": None}))
            logger.info("=" * 50)
            logger.info(f"[{step_idx}/{len(steps)}] HTTP 测速（串行，{DOWNLOAD_CONNS} 连接/节点）")
            logger.info("=" * 50)
            await run_speed_test(mihomo, active_speed, results_dict)
            # 阶段小结：成功/最快/平均
            done = [results_dict[n.name] for n in active_speed if n.name in results_dict]
            spd_ok = [r for r in done if r.speed is not None]
            if spd_ok:
                best_r = max(spd_ok, key=lambda r: r.speed or 0)
                avg_spd = sum(r.speed or 0 for r in spd_ok) / len(spd_ok)
                fail_n = len(done) - len(spd_ok)
                logger.info(
                    "测速完成: 成功 %d/%d | 最快 %.1fMB/s (%s) | 平均 %.1fMB/s%s",
                    len(spd_ok), len(done), best_r.speed or 0,
                    _flag_to_text(best_r.node.name), avg_spd,
                    f" | 失败 {fail_n}" if fail_n else "")
            else:
                logger.info("测速完成: %d 个节点均未测出速度", len(done))
            step_idx += 1

        # 阶段3(补测): 测速完成后，对仍超时的节点重新测 TCP（直连 + 隧道），恢复的补测速
        if mode not in ("streaming", "quick"):
            phase = "补测超时节点"
            timeout_nodes = [n for n in nodes
                             if n.name in results_dict
                             and results_dict[n.name].tcp_ping is None
                             and results_dict[n.name].tcp_probe is not True]
            if timeout_nodes:
                logger.info("=" * 50)
                logger.info(f"补测超时节点: {len(timeout_nodes)} 个（直连重试 + 隧道重试）")
                logger.info("=" * 50)
                revived = set()
                # 直连重试（UDP 节点由 run_tcp_ping 自动跳过，交给隧道重试）
                retry_tcp = await run_tcp_ping(timeout_nodes)
                for n in timeout_nodes:
                    v = retry_tcp.get(n.name)
                    if v is not None and v[0] is not None and n.name in results_dict:
                        results_dict[n.name].tcp_ping = v[0]
                        if not is_udp_node(n):
                            results_dict[n.name].tcp_loss = 3 - v[1]
                        revived.add(n.name)
                # 隧道重试
                still_dead = [n for n in timeout_nodes if retry_tcp.get(n.name) is None
                              or retry_tcp.get(n.name)[0] is None]
                if still_dead and mihomo.binary_path and os.path.isfile(mihomo.binary_path):
                    retry_probe = await run_tcp_probe_pool(mihomo.binary_path, still_dead)
                    for n in still_dead:
                        ok = retry_probe.get(n.name)
                        if ok is not None and n.name in results_dict:
                            results_dict[n.name].tcp_probe = ok
                            if ok:
                                revived.add(n.name)
                # 新恢复的节点补跑测速（不在原测速队列中的才补）
                to_test = [n for n in timeout_nodes
                           if n.name in revived and n.name not in {x.name for x in active_speed}]
                if to_test:
                    logger.info(
                        f"补测恢复 {len(to_test)} 个节点，补跑测速...",
                        extra=_ev("retest_speed", {"nodes": [n.name for n in to_test]}))
                    await run_speed_test(mihomo, to_test, results_dict)
                still_dead_n = sum(
                    1 for n in timeout_nodes
                    if results_dict[n.name].tcp_ping is None
                    and results_dict[n.name].tcp_probe is not True)
                logger.info(
                    f"补测完成: 恢复 {len(revived)} 个，仍超时 {still_dead_n} 个",
                    extra=_ev("retest_done", {"revived": sorted(revived),
                                              "still_dead": still_dead_n}))

        # 阶段4: 流媒体 + IP + 网页模拟（默认 4 路并行，--workers 可调）
        phase = "流媒体/IP/网页检测"
        need_stream = mode != "basic"
        need_ip = (mode == "full") and not fast
        need_web = (mode == "full") and not fast  # 标准测试/完整测速附带；网页模拟依赖 IP 归属选站点

        # v4.28.0：死节点（直连 TCP 与隧道探测均不通）如实标注并跳过流媒体/IP/网页检测，
        # 不浪费时间与 IP 源配额。tcp_probe=None（探测池不可用）不算死，照常测不误杀；
        # streaming-only 模式无 TCP 阶段，不参与标注。
        dead_names = set()
        if mode not in ("streaming", "quick"):
            dead_names = {n.name for n in nodes
                          if results_dict[n.name].tcp_ping is None
                          and results_dict[n.name].tcp_probe is not True}
            if dead_names:
                skip_services = streaming_services or FULL_STREAMING_SERVICES
                for name in dead_names:
                    r = results_dict[name]
                    if not r.error:
                        r.error = "节点不可达"
                    if need_stream:
                        r.streaming = {svc["id"]: "跳过(节点不可达)" for svc in skip_services}
                    if need_ip:
                        r.ip_info = {"error": "节点不可达"}
                    if need_web:
                        r.webpage = {"avg_ms": -1, "error": "节点不可达"}
                logger.info(
                    "不可达节点 %d 个：已标注「节点不可达」，跳过流媒体/IP/网页检测",
                    len(dead_names),
                    extra=_ev("dead_nodes_skipped", {"count": len(dead_names),
                                                     "nodes": sorted(dead_names)}))

        if (need_stream or need_ip or need_web) and mode != "quick" and not (mihomo.binary_path and os.path.isfile(mihomo.binary_path)):
            # 纯流媒体模式此前无二进制检查（非流媒体模式已在阶段2前拦截）
            logger.error("mihomo 不可用，跳过流媒体/IP/网页检测")
            return _finish_partial(results_dict, mode, output_mode, t_start, sort_by,
                                   reason="mihomo_missing")
        if (need_stream or need_ip or need_web) and mode != "quick":
            node_tasks = [(n, need_stream, need_ip, need_web)
                          for n in active_all if n.name not in dead_names]
            if workers > 1:
                pool = MihomoWorkerPool(mihomo.binary_path, workers)
                if await pool.start():
                    used_pool = True
                    logger.info(
                        f"mihomo 并行池就绪: {len(pool.workers)} workers（流媒体/IP/网页）",
                        extra=_ev("worker_pool_start", {"workers": len(pool.workers)}))
                    logger.info("=" * 50)
                    logger.info(f"[{step_idx}/{len(steps)}] 流媒体/IP/网页检测（并行 {len(pool.workers)} 路）")
                    logger.info("=" * 50)
                    await _run_node_pipeline(pool, node_tasks, results_dict, streaming_services)
                else:
                    logger.warning("并行池不可用，回退串行模式")

            if not used_pool:
                # 串行路径：引擎可能尚未启动（流媒体-only 模式）
                if not mihomo.process:
                    mihomo.generate_config(active_all)
                    await mihomo.start()
                logger.info("=" * 50)
                logger.info(f"[{step_idx}/{len(steps)}] 流媒体/IP/网页检测（串行）")
                logger.info("=" * 50)
                test_nodes = [n for n in active_all if n.name not in dead_names]  # v4.28.0：死节点跳过
                if need_stream:
                    await run_streaming_test(mihomo, test_nodes, results_dict, streaming_services)
                if need_ip:
                    await run_ip_quality_test(mihomo, test_nodes, results_dict)
                if need_web:
                    await run_webpage_test(mihomo, test_nodes, results_dict)
            step_idx += 1

    except KeyboardInterrupt:
        interrupted = True  # v4.36.0：中断路径 run_end 记 completed=False + reason=interrupted
        logger.warning("用户中断测试，正在生成当前结果...（中断阶段: %s）", phase,
                       extra=_ev("user_interrupt", {"phase": phase}))
    except asyncio.CancelledError:
        # asyncio.run 下 Ctrl+C 以 CancelledError 抛出，吞掉后继续生成部分结果
        interrupted = True  # v4.36.0：同上
        logger.warning("用户中断测试，正在生成当前结果...（中断阶段: %s）", phase,
                       extra=_ev("user_interrupt", {"phase": phase}))
    except Exception:
        logger.exception("mihomo 测试异常", extra=_ev("run_exception", {"phase": phase}))
    finally:
        # 清理必须尽力完成：外层任务已取消时用 shield 让 stop 在后台跑完，
        # 进程级另有 atexit 同步兜底，防止孤儿 mihomo 与含密码临时 yaml 残留
        if pool:
            try:
                await asyncio.shield(pool.stop())
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("worker 池停止异常", exc_info=True)
        try:
            await asyncio.shield(mihomo.stop())
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("mihomo 停止异常", exc_info=True)
        logger.info("mihomo 已停止", extra=_ev("mihomo_stop", {}))

    # Step 7: 生成报告
    phase = "生成报告"
    total_time = time.monotonic() - t_start
    _mark_reuse(list(results_dict.values()))  # 复用检测四档（依赖 IP 数据，无则空转）
    report_ts = _new_report_timestamp()  # v4.29.0：PNG/JSON 共享时间戳（毫秒防同秒覆盖）
    run_bytes = int(state._RUN_BYTES)
    logger.info("=" * 50)
    logger.info("生成报告...")
    logger.info("=" * 50)
    try:
        img_path = generate_report_image(
            list(results_dict.values()), mode, total_time, sort_by,
            display_mode=output_mode, report_ts=report_ts, run_bytes=run_bytes,
        )
    except Exception:
        logger.exception("报告图片生成失败，仅导出 JSON 数据")
        img_path = ""
    logger.info("=" * 50)
    if interrupted:
        logger.warning(
            "测试中断，已生成部分结果（共 %d 个节点）", len(nodes),
            extra=_ev("run_end", {
                "completed": False,
                "reason": "interrupted",
                "total_seconds": round(total_time, 1),
                "nodes": len(nodes),
                "mode": output_mode,
                "report": img_path,
            }),
        )
    else:
        logger.info(
            "测试完成! 耗时 %.0f 秒，共 %d 个节点", total_time, len(nodes),
            extra=_ev("run_end", {
                "completed": True,
                "reason": "completed",
                "total_seconds": round(total_time, 1),
                "nodes": len(nodes),
                "mode": output_mode,
                "report": img_path,
            }),
        )
    if mode != "streaming":
        direct_ok = sum(1 for r in results_dict.values() if r.tcp_ping is not None)
        probe_only = sum(1 for r in results_dict.values() if r.tcp_ping is None and r.tcp_probe)
        reach_msg = f"{_pad_right('可达', 14)}: 直连 {direct_ok}/{len(nodes)}"
        if probe_only:
            reach_msg += f" + 隧道 {probe_only}"
        logger.info(reach_msg)
    unlocked = sum(
        1 for r in results_dict.values()
        if any("解锁" in v or "可用" in v for v in r.streaming.values())
    ) if any(r.streaming for r in results_dict.values()) else -1
    if unlocked >= 0:
        logger.info(f"{_pad_right('流媒体解锁节点', 14)}: {unlocked}/{len(nodes)}")
    # 同时导出 JSON
    try:
        json_path = export_results_json(list(results_dict.values()), mode,
                                        display_mode=output_mode,
                                        report_ts=report_ts, run_bytes=run_bytes)
    except Exception:
        logger.exception("JSON 导出失败")
        json_path = ""

    append_run(list(results_dict.values()), mode, output_mode, report_ts, json_path)  # v4.29.0：节点档案归档
    try:
        # v4.31.0：测后产物自动清理（静默执行，异常不影响报告）
        st = load_settings()
        cl = cleanup_outputs(st.get("keep_reports", KEEP_REPORTS_DEFAULT),
                             st.get("keep_logs_days", KEEP_LOGS_DAYS_DEFAULT))
        if cl["reports_deleted"] or cl["logs_deleted"]:
            logger.info("产物清理: 报告 -%d 份、日志 -%d 个",
                        cl["reports_deleted"], cl["logs_deleted"],
                        extra=_ev("profiles_cleanup", cl))
    except Exception:
        pass

    logger.info(f"{_pad_right('报告', 14)}: {img_path}", extra=_ev("report_done", {"path": img_path}))
    if json_path:
        logger.info(f"{_pad_right('数据', 14)}: {json_path}", extra=_ev("json_export_done", {"path": json_path}))
    if _LOG_FILE:
        logger.info(f"{_pad_right('日志', 14)}: {_LOG_FILE}")
    logger.info("=" * 50)
    try:
        print_console_summary(list(results_dict.values()), sort_by)
    except Exception:
        pass  # 控制台小结失败不影响主流程
    return img_path

__all__ = ['_finish_partial', '_run_node_pipeline', 'run_test']
