#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IP 质量检测：多源回退 / 风险评分 / 复用检测"""
import asyncio
import re

import aiohttp
from tqdm import tqdm

from .config import *
from .engine import *
from .logging_setup import *
from .models import *
from .utils import *

def _log_ip_details(node_name: str, ip_info: dict) -> None:
    """JSONL 记录单节点 IP 检测结果"""
    logger.debug(
        "IP %s: %s 风险=%s", node_name, ip_info.get("ip", "?"),
        ip_info.get("risk_score", "?"),
        extra=_ev("ip_done", {
            "node": node_name, "ip": ip_info.get("ip"),
            "risk_score": ip_info.get("risk_score"),
            "share_level": ip_info.get("share_level"),
            "asn": ip_info.get("asn"),
            "org": ip_info.get("org"),
            "source": ip_info.get("source"),
        }))


def _heuristic_risk_score(info: dict) -> int:
    """启发式风控评分 0-100"""
    risk = 0
    if info.get("is_datacenter"):
        risk += 20
    if info.get("is_proxy"):
        risk += 25
    if info.get("is_vpn"):
        risk += 20
    if info.get("is_tor"):
        risk += 35
    if info.get("is_abuser"):
        risk += 25
    if info.get("is_crawler"):
        risk += 10
    return min(risk, 100)


def _heuristic_share_level(info: dict) -> str:
    """估算共享人数级别"""
    if info.get("is_datacenter"):
        if info.get("datacenter") is not None:
            return "1000-10000+"
        return "100-1000"
    if info.get("is_proxy") or info.get("is_vpn"):
        return "100-1000"
    if info.get("is_mobile"):
        return "10-100"
    return "1-10"


def _ipapi_com_to_info(data: dict) -> dict:
    """ip-api.com 响应（fields 限定）→ 统一 IP 信息结构

    v4.19.0 主源。免费版限 http + 45 请求/分钟/出口 IP，字段：
    countryCode/city/isp/org/as/asname/proxy/hosting/mobile/query。
    风控标志 proxy（公共代理）/hosting（机房托管）/mobile（移动网络）。
    """
    as_txt = data.get("as", "")
    m = re.match(r"AS(\d+)", as_txt or "")
    info = {
        "ip": data.get("query", ""),
        "country": data.get("countryCode", ""),
        "city": data.get("city", ""),
        "isp": data.get("isp", ""),
        "asn": f"AS{m.group(1)}" if m else "",
        "org": data.get("org", ""),
        "is_datacenter": bool(data.get("hosting")),
        "is_proxy": bool(data.get("proxy")),
        "is_vpn": None,          # 该源无 VPN 标志，不编造
        "is_tor": None,          # 该源无 Tor 标志，不编造
        "is_abuser": None,
        "is_mobile": bool(data.get("mobile")),
        "is_crawler": None,
        "source": "ip-api.com",
    }
    info["risk_score"] = _heuristic_risk_score(info)
    info["share_level"] = _heuristic_share_level(info)
    info["is_native"] = None
    return info


def _ipapi_to_info(data: dict) -> dict:
    """ipapi.is 响应（扁平字段）→ 统一 IP 信息结构

    免费接口实测返回扁平字段：ip/is_bogon/is_datacenter/is_tor/is_proxy/
    is_vpn/is_abuser/company_name/asn_num/asn_org/cc/lat/lon（无城市、
    无 is_mobile/is_crawler 字段）。
    """
    cc = data.get("cc", "")
    asn_num = data.get("asn_num", "")
    asn_org = data.get("asn_org", "")
    company = data.get("company_name", "")
    info = {
        "ip": data.get("ip", ""),
        "country": cc,
        "city": "",
        "isp": company,
        "asn": f"AS{asn_num}" if asn_num else "",
        "org": asn_org or company,
        "is_datacenter": data.get("is_datacenter", False),
        "is_proxy": data.get("is_proxy", False),
        "is_vpn": data.get("is_vpn", False),
        "is_tor": data.get("is_tor", False),
        "is_abuser": data.get("is_abuser", False),
        "is_mobile": data.get("is_mobile", False),
        "is_crawler": data.get("is_crawler", False),
        "datacenter": data.get("datacenter"),
        "source": "ipapi.is",
    }
    info["risk_score"] = _heuristic_risk_score(info)
    info["share_level"] = _heuristic_share_level(info)
    info["is_native"] = None
    return info


def _ipwho_to_info(data: dict) -> dict:
    """ipwho.is 响应 → 统一 IP 信息结构

    免费接口（含 ?security=1 参数）实测无 security 字段、type 恒为
    IPv4/IPv6：无风控数据时类型/风险置 None（报告显示 --），不编造。
    """
    location = data.get("connection", {})
    sec = data.get("security") or {}
    ip_type = (data.get("type") or "").lower()
    has_sec = bool(sec)
    info = {
        "ip": data.get("ip", ""),
        "country": data.get("country_code", ""),
        "city": data.get("city", ""),
        "isp": location.get("isp", ""),
        "asn": f"AS{location.get('asn', '')}" if location.get("asn") else "",
        "org": location.get("org", ""),
        "is_datacenter": None,
        "is_proxy": None,
        "is_vpn": None,
        "is_tor": None,
        "is_abuser": None,
        "is_mobile": None,
        "is_crawler": None,
        "source": "ipwho.is",
    }
    if has_sec:
        info["is_datacenter"] = bool(sec.get("hosting")) or ip_type in ("hosting", "business")
        info["is_proxy"] = bool(sec.get("proxy") or sec.get("anonymous")) or ip_type == "proxy"
        info["is_vpn"] = bool(sec.get("vpn"))
        info["is_tor"] = bool(sec.get("tor"))
        info["is_mobile"] = ip_type == "mobile"
    info["risk_score"] = _heuristic_risk_score(info) if has_sec else None
    info["share_level"] = _heuristic_share_level(info) if has_sec else "--"
    info["is_native"] = None
    return info


def _ipsb_to_info(data: dict) -> dict:
    """api.ip.sb 响应 → 统一 IP 信息结构（无风控字段，不编造风险值）"""
    info = {
        "ip": data.get("ip", ""),
        "country": data.get("country_code", ""),
        "city": data.get("city", ""),
        "isp": data.get("isp", ""),
        "asn": f"AS{data.get('asn', '')}" if data.get("asn") else "",
        "org": data.get("organization", ""),
        "is_datacenter": None, "is_proxy": None, "is_vpn": None, "is_tor": None,
        "is_abuser": None, "is_mobile": None, "is_crawler": None,
        "source": "api.ip.sb",
    }
    info["risk_score"] = None  # 该源无风控数据
    info["share_level"] = "--"
    info["is_native"] = None
    return info


IP_SOURCES = [
    # v4.19.0 主源：ip-api.com 免费版经机场出口实测可用且带 proxy/hosting/mobile 标志
    # （http 明文 + fields 限定；限速 45 请求/分钟/出口 IP，429 时现有逻辑退避重试后换源）
    ("http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,"
     "city,isp,org,as,asname,proxy,hosting,mobile,query", _ipapi_com_to_info),
    # 回退源：ipapi.is 风控字段最全（vpn/tor/abuser/crawler/datacenter），
    # 但实测屏蔽多数机场出口 IP（ClientConnectorError），保留给未被屏蔽的出口
    ("https://api.ipapi.is", _ipapi_to_info),
    # 回退源：免费版无 security 字段（?security=1 参数实测无效），仅地理+ASN
    ("https://ipwho.is/?security=1", _ipwho_to_info),
    # 最后回退：仅地理+ASN，无风控字段
    ("https://api.ip.sb/geoip", _ipsb_to_info),
]


async def check_ip_quality(session: aiohttp.ClientSession, proxy: str) -> dict:
    """通过代理检测出口 IP 质量（多源回退：ip-api.com → ipapi.is → ipwho.is → api.ip.sb）"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    last_err = ""
    for url, mapper in IP_SOURCES:
        for attempt in range(2):  # 429/瞬时错误退避重试一次，避免误降级到无风控字段的回退源
            try:
                async with session.get(
                    url,
                    proxy=proxy,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=IP_QUALITY_TIMEOUT),
                ) as resp:
                    if resp.status == 429:
                        last_err = "HTTP 429 限流"
                        logger.debug("IP 源 %s 限流，退避重试", url,
                                     extra=_ev("ip_source_attempt",
                                               {"source": url, "ok": False,
                                                "error": last_err, "retry": attempt + 1}))
                        await asyncio.sleep(1.0 + attempt)
                        continue
                    if resp.status != 200:
                        last_err = f"HTTP {resp.status}"
                        logger.debug("IP 源 %s 返回 %s，换下一个源", url, last_err,
                                     extra=_ev("ip_source_attempt",
                                               {"source": url, "ok": False, "error": last_err}))
                        break
                    data = await resp.json()
                info = mapper(data)
                if not info.get("ip"):
                    last_err = "响应无 IP 字段"
                    logger.debug("IP 源 %s 响应无 IP 字段，换下一个源", url,
                                 extra=_ev("ip_source_attempt",
                                           {"source": url, "ok": False, "error": last_err}))
                    break
                logger.debug("IP 源 %s 成功", url,
                             extra=_ev("ip_source_attempt", {"source": url, "ok": True}))
                return info
            except Exception as e:
                last_err = _safe_exc_str(e)
                logger.debug("IP 源 %s 失败: %s", url, _safe_exc_str(e),
                             extra=_ev("ip_source_attempt",
                                       {"source": url, "ok": False,
                                        "error": _safe_exc_str(e)[:200]}))
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
    return {"error": last_err or "所有IP源均失败"}


async def run_ip_quality_test(mihomo: MihomoEngine, nodes: list[ProxyNode],
                               results: dict[str, TestResult]) -> None:
    """运行 IP 风控检测"""
    pbar = tqdm(total=len(nodes), desc="IP检测", unit="节点", mininterval=1.0, leave=False)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_pbar_ticker(pbar, stop))
    ssl_ctx = _no_verify_ssl()
    # 每次请求用独立连接，避免连接池复用导致 ipapi.is 缓存
    seen_ips = set()  # 与并行路径一致：同 IP 节点全集标记
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
            # 每次创建新 session，确保走正确的出口
            async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True),
                    max_field_size=65536, max_line_size=65536) as session:
                ip_info = await check_ip_quality(session, proxy)
                if node.name in results:
                    results[node.name].ip_info = ip_info
                    # 标记 IP 是否与其他节点相同
                    curr_ip = ip_info.get("ip", "")
                    if curr_ip:
                        if curr_ip in seen_ips:
                            results[node.name].ip_info["same_ip_warning"] = True
                        seen_ips.add(curr_ip)
                risk = ip_info.get("risk_score")
                risk = "?" if risk is None else risk
                ip_addr = ip_info.get("ip", "?")
                _log_ip_details(node.name, ip_info)
                pbar.set_postfix_str(f"{display} {ip_addr} 风险:{risk}%", refresh=False)
                pbar.update(1)
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        pbar.close()


def _mark_reuse(results: list[TestResult]) -> None:
    """复用检测四档（借鉴 SSRSpeedN：完全/中转/落地复用）：
    - 完全复用：入口（server:port）与落地 IP 都与其他节点相同
    - 中转复用：入口相同、落地 IP 不同（同一台入口中转）
    - 落地复用：入口不同、落地 IP 相同（多个入口共用同一落地）
    结果写入 ip_info["reuse"]；无落地 IP 数据时不标记。O(n)。
    """
    exit_cnt: dict = {}
    entry_cnt: dict = {}
    for r in results:
        ip = (r.ip_info or {}).get("ip", "")
        if not ip or not r.node.server:
            continue  # 空 server 不参与入口计数（避免空键误判）
        entry_key = f"{r.node.server}:{r.node.port}"  # 入口含端口：同主机不同端口不算同一入口
        exit_cnt[ip] = exit_cnt.get(ip, 0) + 1
        entry_cnt[entry_key] = entry_cnt.get(entry_key, 0) + 1
    for r in results:
        ip = (r.ip_info or {}).get("ip", "")
        if not ip:
            continue
        entry_key = f"{r.node.server}:{r.node.port}"
        same_entry = entry_cnt.get(entry_key, 0) > 1
        same_exit = exit_cnt.get(ip, 0) > 1
        if same_entry and same_exit:
            r.ip_info["reuse"] = "完全复用"
        elif same_entry:
            r.ip_info["reuse"] = "中转复用"
        elif same_exit:
            r.ip_info["reuse"] = "落地复用"

__all__ = ['_log_ip_details', '_heuristic_risk_score', '_heuristic_share_level', '_ipapi_com_to_info', '_ipapi_to_info', '_ipwho_to_info', '_ipsb_to_info', 'IP_SOURCES', 'check_ip_quality', 'run_ip_quality_test', '_mark_reuse']
