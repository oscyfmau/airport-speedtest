#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅解析器：协议解析 / 订阅拉取与解码 / 去重 / 流量信息捕获 / 油管源解析"""
import json
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

import requests as _requests
import yaml

from . import state
from .config import *
from .logging_setup import *
from .models import *
from .utils import *

# 可选依赖本地导入（v4.10 模块化后 utils 的探测标志 HAS_* 经 * 透出，但模块名不透出；
# 不本地导入会 NameError 被静默降级，cloudscraper 反爬回退与 yt-dlp 油管源实际失效）
try:
    import cloudscraper
except ImportError:
    cloudscraper = None


try:
    import yt_dlp
except ImportError:
    yt_dlp = None

def _parse_userinfo(headers) -> dict:
    """解析订阅响应头 subscription-userinfo（upload/download/total/expire）"""
    h = ""
    try:
        h = headers.get("subscription-userinfo", "")
    except Exception:
        return {}
    info: dict = {}
    for part in h.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if v.isdigit():
                info[k] = int(v)
    return info


class _YtDlpNullLogger:
    """吞掉 yt-dlp 全部输出（直连失败属预期，由本模块 logger 记录）"""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def resolve_youtube_download_url(timeout: int = 15, proxy: str = None) -> str:
    """解析油管视频直链（googlevideo），失败返回空串。每次运行开始时调用一次。

    依赖 yt-dlp（处理签名解密与 PO token）；格式优先级 137/136/22/18/best；
    视频不可用或解析失败时尝试下一个视频 ID；总耗时上限 30 秒。
    proxy 为空时走本机直连（尊重环境代理变量），否则经指定 HTTP 代理（节点隧道）。
    """
    if state._YOUTUBE_DL_URL:
        return state._YOUTUBE_DL_URL
    if not HAS_YTDLP or yt_dlp is None:
        logger.warning("未安装 yt-dlp，跳过油管测速源（pip install yt-dlp）")
        return ""
    opts = {
        "format": "137/136/22/18/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": timeout,
        "logger": _YtDlpNullLogger(),
    }
    if proxy:
        opts["proxy"] = proxy
    t_start = time.monotonic()
    for vid in YOUTUBE_VIDEO_IDS:
        if time.monotonic() - t_start > 30:
            break
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(vid, download=False)
                formats = (info or {}).get("formats") or []
                selected = (info or {}).get("format_id")
                # 优先取选中格式的直链，否则取第一个带 url 的格式
                for f in formats:
                    if selected and f.get("format_id") == selected and f.get("url"):
                        state._YOUTUBE_DL_URL = f["url"]
                        return state._YOUTUBE_DL_URL
                for f in formats:
                    if f.get("url"):
                        state._YOUTUBE_DL_URL = f["url"]
                        return state._YOUTUBE_DL_URL
        except Exception as e:
            logger.debug(
                "yt-dlp 解析失败 videoId=%s: %s", vid, e,
                extra=_ev("yt_source_attempt",
                          {"video_id": vid, "proxy": bool(proxy), "error": _safe_exc_str(e)[:300]}))
            continue
    return ""


def parse_vmess(uri: str) -> Optional[ProxyNode]:
    """解析 vmess:// Base64 JSON"""
    try:
        raw = _remove_prefix(uri, "vmess://")
        data = json.loads(b64decode_pad(raw))
        extra = {
            "uuid": data.get("id", ""),
            "alterId": data.get("aid", 0),
            "alter-id": data.get("aid", 0),
            "cipher": data.get("scy", "auto") or "auto",
        }
        # tls 判定：白名单式（v2rayN 禁用 TLS 写 "tls":"none"/""，真值判断会误判开启 TLS）
        if str(data.get("tls", "")).lower() in ("tls", "true", "1"):
            extra["tls"] = True
            if data.get("sni"):
                extra["servername"] = data["sni"]
            elif data.get("host"):
                extra["servername"] = data["host"]
        net = data.get("net", "")
        if net == "ws":
            extra["network"] = "ws"
            if data.get("path"):
                extra["ws-path"] = data["path"]
            if data.get("host"):
                extra["ws-headers"] = {"Host": data["host"]}
        elif net in ("tcp", "kcp", "http", "grpc", "quic", "h2"):
            extra["network"] = net
        if net == "grpc":
            # v2rayN 的 vmess grpc 把 serviceName 放在 path 字段
            svc = data.get("serviceName") or data.get("path")
            if svc:
                extra["grpc-opts"] = {"grpc-service-name": svc}
        # VMess "aid" → alterId / alter-id（兼容新旧版）
        return ProxyNode(
            name=data.get("ps", data.get("add", "")),
            type="vmess",
            server=data.get("add", ""),
            port=int(data.get("port", 0)),
            extra=extra,
        )
    except Exception:
        return None


def _parse_userhost_port(uri: str):
    """统一提取 user/host/port/fragment，正确处理 IPv6"""
    parsed = urlparse(uri)
    user = ""
    if parsed.username:
        user = unquote(parsed.username)
    elif "@" in parsed.netloc:
        user = unquote(parsed.netloc.split("@", 1)[0])
    server = parsed.hostname or ""
    port = parsed.port or 443
    params = parse_qs(parsed.query)
    name = unquote(parsed.fragment) if parsed.fragment else server
    return user, server, port, params, name, parsed


def parse_vless(uri: str) -> Optional[ProxyNode]:
    """解析 vless:// UUID@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"uuid": user, "cipher": "none"}
        sec = params.get("security", [""])[0]
        if sec == "reality":
            extra["reality"] = True
            extra["tls"] = True  # mihomo 要求 reality 同时带 tls: true（实测 -t 报 "REALITY requires TLS"）
            # reality-opts：从 query 参数提取 pbk/sid 等
            opts = {}
            if params.get("pbk"):
                opts["public-key"] = params["pbk"][0]
            if params.get("sid"):
                opts["short-id"] = params["sid"][0]
            if params.get("spx"):
                opts["spiderX"] = params["spx"][0]
            if opts:
                extra["reality-opts"] = opts
        elif sec in ("tls", "xtls"):
            extra["tls"] = True
        if sec in ("reality", "tls", "xtls"):
            # add 为 IP 时 TLS 需要 servername（SNI），否则证书校验失败
            if params.get("sni"):
                extra["servername"] = params["sni"][0]
            elif params.get("host"):
                extra["servername"] = params["host"][0]
        if params.get("flow", [""])[0]:
            extra["flow"] = params["flow"][0]
        extra["network"] = params.get("type", ["tcp"])[0]
        if extra["network"] == "ws":
            if params.get("path"):
                extra["ws-path"] = params["path"][0]
            if params.get("host"):
                extra["ws-headers"] = {"Host": params["host"][0]}
        elif extra["network"] == "grpc":
            svc = (params.get("serviceName") or params.get("path") or [None])[0]
            if svc:
                extra["grpc-opts"] = {"grpc-service-name": svc}
        return ProxyNode(name=name, type="vless", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_trojan(uri: str) -> Optional[ProxyNode]:
    """解析 trojan:// pass@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("allowInsecure"):
            extra["skip-cert-verify"] = params["allowInsecure"][0].lower() == "true"
        return ProxyNode(name=name, type="trojan", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_ss(uri: str) -> Optional[ProxyNode]:
    """解析 ss:// SIP002 格式"""
    try:
        parsed = urlparse(uri)
        raw = parsed.netloc or parsed.path
        name = unquote(parsed.fragment) if parsed.fragment else ""
        # 尝试 SIP002 标准: ss://base64(method:password)@host:port
        if "@" in raw:
            # method:password@host:port 格式
            user_info, host_port = raw.split("@", 1)
            # user_info 可能是 base64 编码
            try:
                decoded = b64decode_pad(user_info).decode()
                if ":" in decoded:
                    method, password = decoded.split(":", 1)
                else:
                    method, password = "aes-256-gcm", decoded
            except Exception:
                # 明文 userinfo（非 base64）：method:password 直接拆分
                if ":" in user_info:
                    method, password = user_info.split(":", 1)
                else:
                    method, password = "aes-256-gcm", user_info
            hp = host_port.rsplit(":", 1)
            server = hp[0].strip("[]")  # IPv6 剥离方括号
            port = int(hp[1]) if len(hp) > 1 else 443
        else:
            # 纯 base64: ss://base64(method:password@host:port)
            decoded = b64decode_pad(raw).decode()
            # method:password@host:port
            user_info, host_port = decoded.split("@", 1)
            method, password = user_info.split(":", 1)
            hp = host_port.rsplit(":", 1)
            server = hp[0].strip("[]")  # IPv6 剥离方括号
            port = int(hp[1]) if len(hp) > 1 else 443
        # SIP002 插件参数
        params = parse_qs(parsed.query)
        extra = {"cipher": method, "password": password}
        if params.get("plugin"):
            extra["plugin"] = params["plugin"][0]
        node_name = name or server
        return ProxyNode(name=node_name, type="ss", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_ssr(uri: str) -> Optional[ProxyNode]:
    """解析 ssr:// Base64 编码"""
    try:
        raw = _remove_prefix(uri, "ssr://")
        decoded = b64decode_pad(raw).decode()
        # 格式: server:port:protocol:method:obfs:base64pass/?params
        parts = decoded.split("/?", 1)
        main = parts[0]
        # SSR 格式：server:port:protocol:method:obfs:password_base64
        # IPv6 地址可能含冒号，取最后5段
        main_parts = main.split(":")
        if len(main_parts) < 6:
            return None
        server = ":".join(main_parts[:-5]).strip("[]")  # IPv6 剥离方括号
        port = main_parts[-5]
        protocol = main_parts[-4]
        method = main_parts[-3]
        obfs = main_parts[-2]
        b64_pass = main_parts[-1]
        password = b64decode_pad(b64_pass).decode()
        extra = {
            "cipher": method,
            "password": password,
            "protocol": protocol,
            "obfs": obfs,
        }
        node_name = server
        if len(parts) > 1:
            params = parts[1]
            for param in params.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    if k == "obfsparam":
                        try:
                            extra[k] = b64decode_pad(v).decode()
                        except Exception:
                            extra[k] = v  # 明文值（如 tls1.2_ticket_auth）直接保留
                    elif k == "group":
                        # SSR group 参数（base64）作为节点友好名
                        try:
                            node_name = b64decode_pad(v).decode() or server
                        except Exception:
                            pass
                    elif k == "remarks":
                        # remarks 参数（base64 节点名）：优先于默认名
                        try:
                            node_name = b64decode_pad(v).decode() or node_name
                        except Exception:
                            pass
                    else:
                        extra[k] = v
        return ProxyNode(name=node_name, type="ssr", server=server, port=int(port), extra=extra)
    except Exception:
        return None


def parse_hysteria2(uri: str) -> Optional[ProxyNode]:
    """解析 hysteria2:// pass@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("insecure"):
            extra["skip-cert-verify"] = params["insecure"][0].lower() in ("true", "1", "yes")
        # obfs（salamander）参数映射
        if params.get("obfs"):
            extra["obfs"] = params["obfs"][0]
            if params.get("obfs-password"):
                extra["obfs-password"] = params["obfs-password"][0]
        return ProxyNode(name=name, type="hysteria2", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_hysteria(uri: str) -> Optional[ProxyNode]:
    """解析 hysteria:// host:port?params#name （旧版）"""
    try:
        _, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {
            "protocol": "udp",
            "up": params.get("up", ["100"])[0],
            "down": params.get("down", ["100"])[0],
        }
        if params.get("auth"):
            extra["auth_str"] = params["auth"][0]
        if params.get("auth_str"):
            extra["auth_str"] = params["auth_str"][0]
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("insecure"):
            extra["skip-cert-verify"] = params["insecure"][0].lower() in ("true", "1", "yes")
        return ProxyNode(name=name, type="hysteria", server=server, port=port, extra=extra)
    except Exception:
        return None


def _parse_uuid_password(uri: str, type_name: str, allow_insecure: bool) -> Optional[ProxyNode]:
    """解析 UUID/password 型协议（tuic/juicity 共用）"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"uuid": user, "password": params.get("password", [""])[0]}
        if params.get("congestion_control"):
            extra["congestion-controller"] = params["congestion_control"][0]
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if allow_insecure and params.get("insecure"):
            extra["skip-cert-verify"] = params["insecure"][0].lower() in ("true", "1", "yes")
        return ProxyNode(name=name, type=type_name, server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_tuic(uri: str) -> Optional[ProxyNode]:
    """解析 tuic:// UUID@host:port?params#name"""
    return _parse_uuid_password(uri, "tuic", allow_insecure=True)


def parse_anytls(uri: str) -> Optional[ProxyNode]:
    """解析 anytls:// pass@host:port?params#name"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        if params.get("insecure") or params.get("allowInsecure"):
            # 白名单式判定：insecure=0/空值不算开启（与 hysteria2 口径一致）
            val = (params.get("insecure") or params.get("allowInsecure") or [""])[0]
            extra["skip-cert-verify"] = str(val).lower() in ("true", "1", "yes")
        if params.get("fp"):
            extra["client-fingerprint"] = params["fp"][0]
        return ProxyNode(name=name, type="anytls", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_wireguard(uri: str) -> Optional[ProxyNode]:
    """解析 wg:// / wireguard://"""
    try:
        parsed = urlparse(uri)
        extra = {}
        if parsed.username:
            extra["public-key"] = unquote(parsed.username)
        if parsed.password:
            extra["private-key"] = unquote(parsed.password)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname or ""
        params = parse_qs(parsed.query)
        if params.get("address"):
            extra["ip"] = params["address"][0]
        if params.get("dns"):
            extra["dns"] = params["dns"][0]
        if params.get("mtu"):
            extra["mtu"] = int(params["mtu"][0])
        return ProxyNode(name=name, type="wireguard", server=parsed.hostname or "",
                        port=parsed.port or 443, extra=extra)
    except Exception:
        return None


def parse_naive(uri: str) -> Optional[ProxyNode]:
    """解析 naive:// / naiveproxy://"""
    try:
        user, server, port, params, name, parsed = _parse_userhost_port(uri)
        extra = {"username": user}
        if parsed.password:
            extra["password"] = unquote(parsed.password)
        return ProxyNode(name=name, type="naive", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_shadowtls(uri: str) -> Optional[ProxyNode]:
    """解析 shadowtls://"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"password": user, "version": params.get("version", ["3"])[0]}
        if params.get("sni"):
            extra["sni"] = params["sni"][0]
        return ProxyNode(name=name, type="shadowtls", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_juicity(uri: str) -> Optional[ProxyNode]:
    """解析 juicity://"""
    return _parse_uuid_password(uri, "juicity", allow_insecure=False)


def parse_ssh(uri: str) -> Optional[ProxyNode]:
    """解析 ssh://"""
    try:
        user, server, port, params, name, _ = _parse_userhost_port(uri)
        extra = {"username": user}
        if params.get("password"):
            extra["password"] = params["password"][0]
        if params.get("private-key"):
            extra["private-key"] = params["private-key"][0]
        return ProxyNode(name=name, type="ssh", server=server, port=port, extra=extra)
    except Exception:
        return None


def parse_socks(uri: str) -> Optional[ProxyNode]:
    """解析 socks5:// / socks4://"""
    try:
        parsed = urlparse(uri)
        extra = {}
        if parsed.username:
            extra["username"] = unquote(parsed.username)
        if parsed.password:
            extra["password"] = unquote(parsed.password)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname or ""
        return ProxyNode(
            name=name,
            type="socks5",
            server=parsed.hostname or "",
            port=parsed.port or 1080,
            extra=extra,
        )
    except Exception:
        return None


def parse_http(uri: str) -> Optional[ProxyNode]:
    """解析 http:// / https://"""
    try:
        parsed = urlparse(uri)
        extra = {}
        if parsed.username:
            extra["username"] = unquote(parsed.username)
        if parsed.password:
            extra["password"] = unquote(parsed.password)
        name = unquote(parsed.fragment) if parsed.fragment else parsed.hostname or ""
        return ProxyNode(
            name=name,
            type="http",
            server=parsed.hostname or "",
            port=parsed.port or 8080,
            extra=extra,
        )
    except Exception:
        return None


PARSERS = {
    "vmess://": parse_vmess,
    "vless://": parse_vless,
    "trojan://": parse_trojan,
    "ss://": parse_ss,
    "ssr://": parse_ssr,
    "hysteria2://": parse_hysteria2,
    "hysteria://": parse_hysteria,
    "tuic://": parse_tuic,
    "anytls://": parse_anytls,
    "wg://": parse_wireguard,
    "wireguard://": parse_wireguard,
    "naive://": parse_naive,
    "naiveproxy://": parse_naive,
    "shadowtls://": parse_shadowtls,
    "juicity://": parse_juicity,
    "ssh://": parse_ssh,
    "socks5://": parse_socks,
    "socks4://": parse_socks,
    "http://": parse_http,
    "https://": parse_http,
}


URI_PATTERN = re.compile(r"(vmess|vless|trojan|ss|ssr|hysteria2?|tuic|anytls|wg|wireguard|naive|naiveproxy|shadowtls|juicity|ssh|socks[45]|https?)://")


def _looks_like_yaml(text: str) -> bool:
    """判断内容是否 Clash YAML 配置（容忍注释/空行开头）"""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        return s.startswith("proxies:") or "mixed-port" in s
    return False


def detect_and_decode(content: str) -> str:
    """自动检测并解码订阅内容"""
    # 尝试直接判断是否含 URI
    if URI_PATTERN.search(content):
        return content
    # 尝试 Base64 解码
    try:
        decoded = b64decode_pad(content).decode("utf-8", errors="replace")
        if URI_PATTERN.search(decoded):
            return decoded
        # 有些订阅是 base64 的 yaml
        if _looks_like_yaml(decoded):
            return decoded
    except Exception:
        pass
    # 尝试 YAML
    if _looks_like_yaml(content):
        return content
    return content


_SUB_MAX_BYTES = 20 * 1024 * 1024  # 订阅响应体积上限（防恶意端点内存耗尽）


def _read_limited(resp, limit: int = _SUB_MAX_BYTES) -> str:
    """流式读取响应体并限制体积，返回 UTF-8 文本"""
    chunks = []
    total = 0
    for chunk in resp.iter_content(65536):
        total += len(chunk)
        if total > limit:
            raise RuntimeError(f"订阅内容超过 {limit // 1024 // 1024}MB 上限")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _try_fetch(url: str, ua: str) -> str:
    """用指定 UA 获取订阅内容（绕过系统代理）"""
    scraper = None
    try:
        if HAS_CLOUDSCRAPER and cloudscraper is not None:
            scraper = cloudscraper.create_scraper()
            scraper.headers.update({"User-Agent": ua})
            scraper.proxies = {"http": "", "https": ""}
            resp = scraper.get(url, timeout=30, stream=True)
        else:
            raise ImportError("cloudscraper not installed")
    except Exception as e:
        logger.debug(
            "cloudscraper 失败，回退 requests: %s", _safe_exc_str(e),
            extra=_ev("fetch_fallback", {"url": _mask_url(url), "error": _safe_exc_str(e)[:200]}))
        try:
            resp = _requests.get(url, headers={"User-Agent": ua}, timeout=30, stream=True)
        except Exception as e:
            raise RuntimeError(f"订阅下载失败: {_safe_exc_str(e)}") from e
    finally:
        if scraper is not None:
            try:
                scraper.close()
            except Exception:
                pass
    # 捕获订阅流量信息（流量倍率用）：首个带 header 的响应为准
    try:
        if not state._SUB_INFO.get(url):
            info = _parse_userinfo(resp.headers)
            if info.get("download") is not None:
                state._SUB_INFO[url] = info
    except Exception:
        pass
    try:
        return _read_limited(resp)
    finally:
        resp.close()


def parse_subscription_url(url: str) -> list[ProxyNode]:
    """从订阅 URL 下载并解析节点列表，自动尝试多个 UA 找到最多节点"""
    # 不同 UA 返回不同内容，优先用能获取最多真实节点的
    user_agents = [
        "curl/8.0",
        "ClashMeta/1.0",
        "v2rayN/6.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    ]

    best_nodes = []

    for ua in user_agents:
        try:
            content = _try_fetch(url, ua)
            # 跳过 Cloudflare 挑战页
            if "Attention Required" in content or "Cloudflare" in content[:300]:
                logger.warning("UA %s 返回 Cloudflare 挑战页，跳过", ua)
                continue
            nodes = parse_subscription_content(content)
            if len(nodes) > len(best_nodes):
                best_nodes = nodes
            logger.info("UA %s 解析到 %d 个节点", ua, len(nodes))
        except Exception as e:
            logger.warning("UA %s 拉取订阅失败: %s", ua, _safe_exc_str(e))
            continue

    if not best_nodes and user_agents:
        # 全部失败，最后再用 cloudscraper 试一次
        scraper = None
        try:
            if HAS_CLOUDSCRAPER and cloudscraper is not None:
                scraper = cloudscraper.create_scraper()
                resp = scraper.get(url, timeout=30)
            else:
                raise ImportError("cloudscraper not installed")
            resp.encoding = "utf-8"
            best_nodes = parse_subscription_content(resp.text)
        except Exception as e:
            logger.warning("cloudscraper 拉取订阅失败: %s", _safe_exc_str(e))
        finally:
            if scraper is not None:
                try:
                    scraper.close()
                except Exception:
                    pass

    return best_nodes


def parse_subscription_content(content: str) -> list[ProxyNode]:
    """解析订阅内容，返回节点列表"""
    decoded = detect_and_decode(content)
    nodes = []

    # 尝试 YAML 格式（Clash 配置）
    if _looks_like_yaml(decoded):
        try:
            yaml_data = yaml.safe_load(decoded)
            if isinstance(yaml_data, dict) and "proxies" in yaml_data:
                for p in yaml_data["proxies"]:
                    try:
                        nodes.append(_yaml_to_node(p))
                    except Exception as e:
                        # 单条坏条目跳过，不拖垮整份 YAML
                         logger.warning("YAML 单条 proxy 解析失败，已跳过: %s", _safe_exc_str(e))
                if nodes:
                    # YAML 路径与 URI 路径统一过滤/去重（不支持类型、重名节点
                    # 会直接导致 mihomo 整份配置加载失败）
                    nodes = [n for n in nodes if _is_valid_node(n)]
                    nodes = _dedupe_nodes(nodes)
                    if nodes:
                        return nodes
        except Exception as e:
            logger.warning("YAML 订阅解析失败，回退逐行解析: %s", _safe_exc_str(e))

    # 逐行解析 URI
    for line in decoded.splitlines():
        line = line.strip()
        if not line:
            continue
        # 跳过注释和非 URI 行
        if line.startswith("#") or line.startswith("//"):
            continue
        node = parse_node_uri(line)
        if node:
            nodes.append(node)

    # 过滤无效节点
    nodes = [n for n in nodes if _is_valid_node(n)]

    return _dedupe_nodes(nodes)


def _sanitize_name(name: str) -> str:
    """清洗节点名：去控制符/换行、限长 100（防 YAML 引号异常与 mihomo 名称空间问题）"""
    s = re.sub(r"[\x00-\x1f\x7f]", "", name or "")
    return s[:100]


def _dedupe_nodes(nodes: list[ProxyNode]) -> list[ProxyNode]:
    """节点名清洗 + 同名节点加后缀去重"""
    seen = {}
    for n in nodes:
        n.name = _sanitize_name(n.name)
        if n.name in seen:
            idx = 2
            while f"{n.name}_{idx}" in seen:
                idx += 1
            n.name = f"{n.name}_{idx}"
        seen[n.name] = n
    return list(seen.values())


def parse_subscription_urls(urls: list) -> list[ProxyNode]:
    """解析多个订阅 URL 并合并节点（跨订阅同名去重）"""
    all_nodes = []
    for i, url in enumerate(urls):
        try:
            logger.info("[%d/%d] 订阅解析中: %s", i + 1, len(urls), _mask_url(url))
            ns = parse_subscription_url(url)
            logger.info("订阅 %s 解析到 %d 个节点", _mask_url(url), len(ns))
            all_nodes.extend(ns)
        except Exception as e:
            logger.warning("订阅 %s 解析失败: %s", _mask_url(url), _safe_exc_str(e))
    return _dedupe_nodes(all_nodes)


def _fetch_sub_usage(urls: list) -> dict:
    """测速后重拉订阅头（每 URL 一次），返回 {url: download 字节}——流量倍率用"""
    out: dict = {}
    for url in urls:
        try:
            r = _requests.get(url, headers={"User-Agent": "ClashMeta/1.0"},
                              timeout=20, stream=True)
            info = _parse_userinfo(r.headers)
            r.close()
            if info.get("download") is not None:
                out[url] = info["download"]
        except Exception:
            continue
    return out


MIHOMO_SUPPORTED_TYPES = {"ss", "ssr", "vmess", "vless", "trojan", "hysteria",
                          "hysteria2", "tuic", "anytls", "wireguard",
                          "socks5", "http", "ssh"}


def _is_valid_node(n: ProxyNode) -> bool:
    """过滤掉非真实节点的条目"""
    # 排除本地地址
    if n.server in ("127.0.0.1", "0.0.0.0", "localhost", "", "::1"):
        return False
    # 排除端口 0
    if n.port == 0:
        return False
    # 排除名字含关键词的信息行
    skip_keywords = ["剩余流量", "套餐到期", "重置", "客户端不支持", "请用官网"]
    for kw in skip_keywords:
        if kw in n.name:
            return False
    # 与 mihomo 内置名称冲突（proxy 与 proxy-group 共用命名空间，重名会整份加载失败）
    if n.name in ("DIRECT", "Auto"):
        logger.warning("节点 %s 与 mihomo 内置名称冲突，已过滤", n.name)
        return False
    # mihomo 不支持的类型（shadowtls/naive/juicity 等）不进测速流程
    if n.type not in MIHOMO_SUPPORTED_TYPES:
        logger.warning("节点 %s 类型 %s 不被 mihomo 支持，已过滤", n.name, n.type)
        return False
    # wireguard 必须有 public-key 与 private-key 才能连通（缺 private-key 会拖垮整份配置）
    if n.type == "wireguard":
        if not n.extra.get("public-key") or not n.extra.get("private-key"):
            logger.warning("节点 %s wireguard 缺少 public-key/private-key，已过滤", n.name)
            return False
    return True


def _yaml_to_node(p: dict) -> ProxyNode:
    """将 Clash YAML proxy 条目转换为 ProxyNode"""
    if not isinstance(p, dict):
        raise ValueError(f"proxy 条目不是字典: {type(p).__name__}")
    extra = {}
    for k, v in p.items():
        if k in ("name", "type", "server", "port"):
            continue
        extra[k] = v
    return ProxyNode(
        name=str(p.get("name", "")),
        type=str(p.get("type", "")),
        server=str(p.get("server", "")),
        port=int(p.get("port") or 0),
        extra=extra,
    )


def parse_node_uri(line: str) -> Optional[ProxyNode]:
    """解析单行 URI"""
    line = line.strip()
    for prefix, parser in PARSERS.items():
        if line.startswith(prefix):
            return parser(line)
    return None


def read_subscribe_urls() -> list[str]:
    """从默认文件读取订阅 URL"""
    urls = []
    if os.path.exists(SUBSCRIBE_FILE):
        # utf-8-sig：兼容 UTF-8 BOM（首行 URL 带 \ufeff 会解析失败）；GBK 失败时回退
        try:
            with open(SUBSCRIBE_FILE, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        except UnicodeDecodeError:
            with open(SUBSCRIBE_FILE, "r", encoding="gbk", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
    return urls

__all__ = ['_parse_userinfo', '_YtDlpNullLogger', 'resolve_youtube_download_url', 'parse_vmess', '_parse_userhost_port', 'parse_vless', 'parse_trojan', 'parse_ss', 'parse_ssr', 'parse_hysteria2', 'parse_hysteria', '_parse_uuid_password', 'parse_tuic', 'parse_anytls', 'parse_wireguard', 'parse_naive', 'parse_shadowtls', 'parse_juicity', 'parse_ssh', 'parse_socks', 'parse_http', 'PARSERS', 'URI_PATTERN', '_looks_like_yaml', 'detect_and_decode', '_try_fetch', 'parse_subscription_url', 'parse_subscription_content', '_dedupe_nodes', 'parse_subscription_urls', '_fetch_sub_usage', 'MIHOMO_SUPPORTED_TYPES', '_is_valid_node', '_yaml_to_node', 'parse_node_uri', 'read_subscribe_urls']
