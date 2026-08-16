#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mihomo 引擎：内核获取与更新 / 配置生成 / 进程管理 / 热重载 / 并行工作池 / TCP 直连检测"""
import asyncio
import gzip
import hashlib
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

import aiohttp
import requests as _requests
import yaml
from tqdm import tqdm
from typing import Optional

from .config import *
from .logging_setup import *
from .models import *
from .procs import *
from .utils import *

async def tcp_ping(host: str, port: int, timeout: float = 3.0) -> Optional[float]:
    """TCP 连接延迟测试，返回毫秒"""
    try:
        t0 = time.monotonic()
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        elapsed = (time.monotonic() - t0) * 1000
        writer.close()
        await writer.wait_closed()
        return elapsed
    except (asyncio.TimeoutError, OSError):
        return None
    except Exception:
        return None


async def tcp_ping_retry(host: str, port: int, attempts: int = 3,
                         timeouts: tuple = (2.0, 3.0, 3.0)) -> tuple[Optional[float], int]:
    """TCP Ping 带重试（瞬态失败容错），返回 (最小延迟ms, 成功次数)——成功次数用于丢包率"""
    best = None
    ok = 0
    for i in range(attempts):
        t = await tcp_ping(host, port, timeouts[min(i, len(timeouts) - 1)])
        if t is not None:
            ok += 1
            best = t if best is None else min(best, t)
        if i < attempts - 1:
            await asyncio.sleep(0.3)  # 重试间隔，给瞬态拥塞恢复时间
    return best, ok


async def run_tcp_ping(nodes: list[ProxyNode], concurrency: int = TCP_PING_CONCURRENCY,
                       attempts: int = 3, timeouts: tuple = (2.0, 3.0, 3.0)) -> dict:
    """并发 TCP Ping 所有节点（UDP/QUIC 系协议节点跳过，由 mihomo 实测可达性）

    attempts/timeouts 为单节点重试参数（默认 3 次；quick 模式 1 次 2s，v4.30.0）。
    返回 {节点名: (最小延迟ms 或 None, 成功次数)}
    """
    sem = asyncio.Semaphore(concurrency)

    async def ping_one(node: ProxyNode) -> tuple[ProxyNode, Optional[float], int]:
        async with sem:
            if is_udp_node(node):
                return node, None, 0
            latency, ok = await tcp_ping_retry(node.server, node.port, attempts=attempts,
                                               timeouts=timeouts)
            return node, latency, ok

    tasks = [ping_one(n) for n in nodes]
    results = {}
    pbar = tqdm(total=len(nodes), desc="TCP Ping", unit="节点", mininterval=1.0, leave=False)
    for coro in asyncio.as_completed(tasks):
        node, latency, ok = await coro
        results[node.name] = (latency, ok)
        if is_udp_node(node):
            label = "UDP跳过"
        elif latency:
            label = f"{latency:.0f}ms"
            if ok < attempts:
                label += f"({attempts - ok}丢)"
        else:
            label = "超时"
        pbar.set_postfix_str(f"{_flag_to_text(node.name)} {label}", refresh=False)
        pbar.update(1)
        logger.debug(
            "TCP %s %s", node.name, label,
            extra=_ev("tcp_ping", {"node": node.name, "type": node.type,
                                   "result": label, "loss": attempts - ok if not is_udp_node(node) else None}))
    pbar.close()
    return results


async def run_tcp_probe_pool(binary_path: str, candidates: list[ProxyNode]) -> dict:
    """TCP 来源B：经 mihomo 隧道并发探测节点可达性（直连失败节点兜底 + UDP 节点）

    每个候选占一个独立 worker（并发 TCP_PROBE_CONCURRENCY 路），
    经节点隧道请求 gstatic 204 判定可达。返回 {节点名: bool}
    """
    if not candidates or not binary_path or not os.path.isfile(binary_path):
        return {}
    size = min(TCP_PROBE_CONCURRENCY, len(candidates))
    pool = MihomoWorkerPool(binary_path, size)
    if not await pool.start():
        return {}
    results: dict = {}
    queue: asyncio.Queue = asyncio.Queue()
    for n in candidates:
        await queue.put(n)
    for _ in pool.workers:
        await queue.put(None)  # 终止哨兵

    ssl_ctx = _verified_ssl()  # v4.35.0：默认校验证书（防出口 MITM）
    pbar = tqdm(total=len(candidates), desc="TCP探测", unit="节点", mininterval=1.0, leave=False)

    async def probe_loop(worker: MihomoWorker):
        while True:
            node = await queue.get()
            if node is None:
                queue.task_done()
                return
            ok = False
            try:
                pbar.set_postfix_str(f"{_flag_to_text(node.name)} 探测中")
                if await worker.load_node(node):
                    try:
                        async with aiohttp.ClientSession(
                                connector=aiohttp.TCPConnector(ssl=ssl_ctx, force_close=True)) as sess:
                            async with sess.get(
                                    "https://www.gstatic.com/generate_204",
                                    proxy=worker.get_proxy_url(),
                                    timeout=aiohttp.ClientTimeout(total=TCP_PROBE_TIMEOUT),
                            ) as resp:
                                ok = resp.status == 204
                    except Exception:
                        ok = False
            except Exception:
                ok = False
            results[node.name] = ok
            logger.debug(
                "隧道探测 %s %s", node.name, "可达" if ok else "不可达",
                extra=_ev("tcp_probe", {"node": node.name, "reachable": ok}))
            pbar.set_postfix_str(
                f"{_flag_to_text(node.name)} {'可达' if ok else '不可达'}", refresh=False)
            queue.task_done()
            pbar.update(1)

    try:
        await asyncio.gather(*[probe_loop(w) for w in pool.workers])
    finally:
        pbar.close()
        await pool.stop()  # 中断/异常时也必须回收探测池，防止泄漏 mihomo 进程
    return results


class MihomoEngine:
    """mihomo (clash-meta) 引擎管理"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.mixed_port = self._find_free_port(7890)
        self.api_port = self._find_free_port(9090, exclude={self.mixed_port})
        self.secret = secrets.token_hex(16)  # 外部控制器 API 认证（防本机进程/DNS 重绑定读取凭据）
        self.binary_path = self._find_or_download()
        self.config_path = ""
        self._ready = False

    @staticmethod
    def _find_free_port(start: int, exclude: set = None) -> int:
        """找可用端口，范围放宽；exclude 集合内的端口跳过（防 mixed/api 碰撞）"""
        import socket
        for port in range(start, 60000):
            if exclude and port in exclude:
                continue
            try:
                with socket.socket() as s:
                    s.bind(("127.0.0.1", port))
                    return port
            except OSError:
                continue
        return start

    @staticmethod
    def _find_or_download() -> str:
        """查找或下载 mihomo 二进制"""
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        # 查找已有二进制
        for f in os.listdir(MIHOMO_DIR):
            if f.startswith("mihomo") and (f.endswith(".exe") or "." not in f):
                return os.path.join(MIHOMO_DIR, f)
        # 需要下载
        print("未找到 mihomo 内核，正在下载...")
        binary = MihomoEngine._download_mihomo()
        if binary:
            return binary
        logger.warning("mihomo 下载失败，部分功能不可用")
        logger.warning("  修复方法：检查网络后重试；或手动下载 mihomo 放入 bin/ 目录；或运行菜单 6 更新内核")
        return ""

    @staticmethod
    def _get_latest_tag() -> str:
        """获取最新 mihomo 版本号，避免 GitHub API 限速"""
        # 方法1: 通过 releases/latest 重定向获取 tag
        try:
            r = _requests.get(
                f"https://github.com/{MIHOMO_REPO}/releases/latest",
                allow_redirects=True, timeout=10,
                proxies=dict(DIRECT_PROXIES),  # v4.28.0：强制直连
            )
            if r.status_code == 200:
                tag = r.url.rstrip("/").split("/")[-1]
                if tag.startswith("v"):
                    return tag
        except Exception:
            pass
        # 方法2: 尝试 GitHub API (可能被限速)
        try:
            r = _requests.get(
                f"https://api.github.com/repos/{MIHOMO_REPO}/releases/latest",
                timeout=10, headers={"User-Agent": "speed_test.py/1.0"},
                proxies=dict(DIRECT_PROXIES),  # v4.28.0：强制直连
            )
            if r.status_code == 200:
                return r.json()["tag_name"]
        except Exception:
            pass
        return ""

    @staticmethod
    def _get_mihomo_version(binary_path: str) -> str:
        """运行 mihomo -v 提取版本号（如 v1.19.29）；二进制缺失/不可执行/解析失败返回空串"""
        try:
            if not binary_path or not os.path.isfile(binary_path):
                return ""
            out = subprocess.run(
                [binary_path, "-v"], capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            m = re.search(r"v\d+\.\d+\.\d+", out.stdout or "")
            if m:
                return m.group(0)
        except Exception:
            pass
        return ""

    @staticmethod
    def _download_mihomo(target_dir: str = None) -> str:
        """下载最新 mihomo 到 target_dir（默认 MIHOMO_DIR），成功返回二进制路径"""
        target_dir = target_dir or MIHOMO_DIR
        os.makedirs(target_dir, exist_ok=True)
        try:
            tag = MihomoEngine._get_latest_tag()
            if not tag:
                return ""

            # 确定平台与 CPU 架构（mihomo 官方发布件：windows/linux/darwin × amd64/arm64）
            system = sys.platform
            machine = platform.machine().lower()
            if machine in ("amd64", "x86_64", "x64"):
                arch = "amd64"
            elif machine in ("arm64", "aarch64"):
                arch = "arm64"
            else:
                logger.warning(f"不支持的 CPU 架构: {machine}，跳过 mihomo 下载")
                return ""
            if system == "win32":
                plat = f"windows-{arch}"
                ext = ".exe"
            elif system == "linux":
                plat = f"linux-{arch}"
                ext = ""
            elif system == "darwin":
                plat = f"darwin-{arch}"
                ext = ""
            else:
                return ""

            # 候选文件名：Windows 官方发布 .zip；Linux/macOS 发布单文件 .gz（gzip，无 zip）
            if ext == ".exe":
                candidates = [
                    f"mihomo-{plat}-{tag}.zip",
                    f"mihomo-{plat}-v1-{tag}.zip",
                    f"mihomo-{plat}.zip",
                    f"mihomo-{plat}-alpha-{tag}.zip",
                ]
            else:
                candidates = [
                    f"mihomo-{plat}-{tag}.gz",
                    f"mihomo-{plat}-v1-{tag}.gz",
                    f"mihomo-{plat}-go124-{tag}.gz",
                ]

            base_url = f"https://github.com/{MIHOMO_REPO}/releases/download/{tag}"
            zip_path = None

            for fname in candidates:
                url = f"{base_url}/{fname}"
                try:
                    print(f"  尝试: {fname}")
                    zip_resp = _requests.get(url, stream=True, timeout=30,
                                              proxies=dict(DIRECT_PROXIES))  # v4.28.0：强制直连
                    if zip_resp.status_code == 200:
                        total = int(zip_resp.headers.get("content-length", 0))
                        zip_path = os.path.join(target_dir, fname)
                        try:
                            with open(zip_path, "wb") as f:
                                downloaded = 0
                                t0 = time.monotonic()
                                for chunk in zip_resp.iter_content(8192):
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total:
                                        pct = downloaded / total * 100
                                        el = time.monotonic() - t0
                                        spd = downloaded / el if el > 0 else 0
                                        eta = (total - downloaded) / spd if spd > 0 else 0
                                        print(f"\r  下载中: {_fmt_size(downloaded)}/{_fmt_size(total)}"
                                              f" {pct:.0f}% {_fmt_size(spd)}/s 剩余{eta:.0f}s",
                                              end="", flush=True)
                                print()  # 结束 \r 进度行，避免后续日志接在同一行
                        except Exception:
                            os.remove(zip_path)  # 中途异常：清理半截压缩包
                            raise
                        logger.info(f"下载完成: {fname} ({_fmt_size(total)}，mihomo {tag})")
                        break
                    else:
                        zip_resp.close()  # 非 200（404/403）：关闭连接再试下一个候选
                except Exception as e:
                    logger.warning(f"下载 {fname} 失败: {_safe_exc_str(e)}")
                    continue

            if not zip_path or not os.path.exists(zip_path):
                return ""

            # v4.35.0：下载校验——mihomo 官方发布件不附带 .sha256 资产（2026-08 实测），
            # 存在同名 .sha256 校验文件时核验 SHA256；缺失时仅做压缩包完整性校验并 WARNING 提示
            try:
                sha_resp = _requests.get(zip_path + ".sha256", timeout=15,
                                         proxies=dict(DIRECT_PROXIES))  # v4.28.0：强制直连
                if sha_resp.status_code == 200:
                    expected = sha_resp.text.strip().split()[0].lower()
                    digest = hashlib.sha256()
                    with open(zip_path, "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 16), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected:
                        logger.error("SHA256 校验失败: %s（期望 %s，实际 %s），已删除",
                                     fname, expected, digest.hexdigest())
                        os.remove(zip_path)
                        return ""
                    logger.info("SHA256 校验通过: %s", fname)
                else:
                    logger.warning("官方未提供 %s 校验文件，仅做压缩包完整性校验", fname + ".sha256")
            except Exception as e:
                logger.warning("SHA256 校验不可用: %s", _safe_exc_str(e))

            # 解压：Windows 为 zip（校验 zip-slip + 完整性）；Linux/macOS 为单文件 gzip
            if ext == ".exe":
                base_real = os.path.realpath(target_dir)
                try:
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        bad = zf.testzip()  # v4.35.0：CRC 完整性校验（截断/损坏包不落盘）
                        if bad is not None:
                            raise RuntimeError(f"压缩包损坏: {bad}")
                        for name in zf.namelist():
                            tgt = os.path.realpath(os.path.join(target_dir, name))
                            if not (tgt == base_real or tgt.startswith(base_real + os.sep)):
                                raise RuntimeError(f"非法压缩包路径: {name}")
                        zf.extractall(target_dir)
                except Exception as e:
                    logger.error(f"解压失败: {e}")
                    os.remove(zip_path)
                    return ""
                os.remove(zip_path)

                # 找到解压后的二进制
                for root, _, files in os.walk(target_dir):
                    for f in files:
                        if "mihomo" in f.lower() and (f.endswith(".exe") or "." not in f):
                            binary_path = os.path.join(root, f)
                            dst = os.path.join(target_dir, f"mihomo{ext}")
                            if binary_path != dst:
                                shutil.move(binary_path, dst)
                            logger.info(f"mihomo {tag} 已就绪: {dst}")
                            return dst
                return ""
            else:
                # gzip 单文件 → 解压为 mihomo（无扩展名），加执行权限
                try:
                    with gzip.open(zip_path, "rb") as gz:
                        data = gz.read()
                    dst = os.path.join(target_dir, "mihomo")
                    with open(dst, "wb") as f:
                        f.write(data)
                    os.chmod(dst, 0o755)
                except Exception as e:
                    logger.error(f"解压失败: {e}")
                    os.remove(zip_path)
                    return ""
                os.remove(zip_path)
                logger.info(f"mihomo 已就绪: {dst}")
                return dst
        except Exception as e:
            logger.error(f"mihomo 下载失败: {e}")
            return ""

    def generate_config(self, nodes: list[ProxyNode]) -> str:
        """生成 Clash 配置文件"""
        config = _build_config_dict(nodes, self.mixed_port, self.api_port, self.secret)
        # 写入临时文件
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="mihomo_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        try:
            os.chmod(path, 0o600)  # v4.35.0：凭据文件权限收紧（POSIX 生效；Windows 无 ACL 语义）
        except OSError:
            pass
        self.config_path = path
        return path

    async def start(self):
        """启动 mihomo 进程"""
        if not self.binary_path:
            raise RuntimeError("mihomo 二进制不存在")
        if self.process and self._ready:
            return
        self.process = _track_proc(subprocess.Popen(
            [self.binary_path, "-f", self.config_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
        # 等待 API 就绪
        auth = {"Authorization": f"Bearer {self.secret}"}
        async with aiohttp.ClientSession() as sess:
            for i in range(30):
                if self.process.poll() is not None:
                    # 进程已退出（配置错误/二进制损坏），无需等满 15s
                    self._ready = False
                    raise RuntimeError("mihomo 进程异常退出（配置或二进制问题）")
                await asyncio.sleep(0.5)
                try:
                    async with sess.get(f"http://127.0.0.1:{self.api_port}/version",
                                        headers=auth, timeout=2) as resp:
                        if resp.status == 200:
                            self._ready = True
                            return
                except Exception:
                    continue
        self._ready = False
        raise RuntimeError("mihomo 启动超时")

    async def stop(self):
        """停止 mihomo"""
        if self.process:
            self.process.terminate()
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self.process.wait),
                    timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await loop.run_in_executor(None, self.process.wait)
            _untrack_proc(self.process)  # 正常回收后注销登记
            self.process = None
            self._ready = False
        # 清理配置
        if self.config_path and os.path.exists(self.config_path):
            try:
                os.remove(self.config_path)
            except Exception:
                pass

    async def switch_proxy(self, name: str) -> bool:
        """切换到指定节点并校验生效（防止测速走错出口）"""
        if not self._ready:
            return False
        async with aiohttp.ClientSession() as sess:
            auth = {"Authorization": f"Bearer {self.secret}"}
            for attempt in range(2):
                try:
                    async with sess.put(
                        f"http://127.0.0.1:{self.api_port}/proxies/Auto",
                        json={"name": name},
                        headers=auth,
                        timeout=5,
                    ) as resp:
                        if resp.status != 204:
                            break
                except Exception:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    return False
                # 校验生效：轮询 Auto 组当前选中节点
                if await _wait_auto_selected(self.api_port, name, secret=self.secret):
                    return True
                if attempt == 0:
                    continue
        return False

    def get_proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.mixed_port}"

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()


def _build_config_dict(nodes: list[ProxyNode], mixed_port: int, api_port: int,
                       secret: str = "") -> dict:
    """构建 Clash 配置字典（单实例全节点 / 并行 worker 单节点共用）"""
    cfg = {
        "mixed-port": mixed_port,
        "external-controller": f"127.0.0.1:{api_port}",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "silent",
        "ipv6": True,  # 允许 IPv6 节点（v4 节点不受影响）
        "proxies": [n.to_clash_proxy() for n in nodes],
        "proxy-groups": [
            {
                "name": "Auto",
                "type": "select",
                "proxies": [n.name for n in nodes] + ["DIRECT"],
            }
        ],
        "rules": [
            "MATCH,Auto",
        ],
    }
    if secret:
        cfg["secret"] = secret  # 外部控制器认证：API 请求需 Authorization: Bearer
    return cfg


async def _wait_auto_selected(api_port: int, name: str, timeout: float = 3.0,
                              interval: float = 0.2, request_timeout: float = 1.0,
                              secret: str = "") -> bool:
    """轮询 mihomo API，直到 Auto 组当前选中节点 == name（引擎与 worker 共用）"""
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    async with aiohttp.ClientSession() as sess:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with sess.get(
                        f"http://127.0.0.1:{api_port}/proxies/Auto",
                        headers=headers,
                        timeout=request_timeout) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data.get("now") == name:
                            return True
            except Exception:
                pass
            await asyncio.sleep(interval)
    return False


class MihomoWorker:
    """单个 mihomo 工作进程：一次只服务一个节点，通过 PUT /configs 热重载切换"""

    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.process: Optional[subprocess.Popen] = None
        self.mixed_port = MihomoEngine._find_free_port(17890)
        self.api_port = MihomoEngine._find_free_port(19090, exclude={self.mixed_port})
        self.secret = secrets.token_hex(16)  # 外部控制器 API 认证
        self.config_path = ""
        self._ready = False

    def _write_config(self, nodes: list[ProxyNode]) -> str:
        config = _build_config_dict(nodes, self.mixed_port, self.api_port, self.secret)
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="mihomo_worker_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        try:
            os.chmod(path, 0o600)  # v4.35.0：凭据文件权限收紧（POSIX 生效；Windows 无 ACL 语义）
        except OSError:
            pass
        self.config_path = path
        return path

    async def _wait_ready(self, timeout: float = 15.0) -> bool:
        auth = {"Authorization": f"Bearer {self.secret}"}
        async with aiohttp.ClientSession() as sess:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    async with sess.get(f"http://127.0.0.1:{self.api_port}/version",
                                        headers=auth, timeout=2) as resp:
                        if resp.status == 200:
                            self._ready = True
                            return True
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        self._ready = False
        return False

    async def start(self) -> bool:
        """以空配置启动 worker"""
        self._write_config([])
        self.process = _track_proc(subprocess.Popen(
            [self.binary_path, "-f", self.config_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
        return await self._wait_ready()

    async def stop(self):
        """停止 worker 并清理配置"""
        if self.process:
            self.process.terminate()
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, self.process.wait), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await loop.run_in_executor(None, self.process.wait)
            _untrack_proc(self.process)  # 正常回收后注销登记
            self.process = None
            self._ready = False
        if self.config_path and os.path.exists(self.config_path):
            try:
                os.remove(self.config_path)
            except Exception:
                pass

    async def _reload_config(self, nodes: list[ProxyNode]) -> bool:
        """PUT /configs 热重载（JSON body: path + payload）"""
        payload = yaml.dump(
            _build_config_dict(nodes, self.mixed_port, self.api_port, self.secret),
            allow_unicode=True, default_flow_style=False)
        async with aiohttp.ClientSession() as sess:
            async with sess.put(
                f"http://127.0.0.1:{self.api_port}/configs?force=true",
                json={"path": "", "payload": payload},
                headers={"Authorization": f"Bearer {self.secret}"},
                timeout=10,
            ) as resp:
                return resp.status == 204

    async def _verify_node(self, name: str, timeout: float = 3.0) -> bool:
        """校验 Auto 组当前选中节点是否为目标节点（共享轮询实现）"""
        return await _wait_auto_selected(self.api_port, name, timeout=timeout,
                                         secret=self.secret)

    async def load_node(self, node: ProxyNode) -> bool:
        """热加载单节点配置并校验生效；失败则重启该 worker 兜底"""
        if not self._ready:
            return False
        for attempt in range(2):
            try:
                if await self._reload_config([node]) and await self._verify_node(node.name):
                    return True
            except Exception:
                pass
            if attempt == 0:
                # 热重载失败 → 重启 worker（带目标节点配置重新拉起）
                logger.warning("worker 热重载失败，重启中 (node=%s)", node.name)
                await self.stop()
                self._write_config([node])
                self.process = _track_proc(subprocess.Popen(
                    [self.binary_path, "-f", self.config_path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ))
                if not await self._wait_ready():
                    return False
        return False

    def get_proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.mixed_port}"


class MihomoWorkerPool:
    """mihomo 并行工作进程池：N 个 worker 同时服务 N 个节点"""

    def __init__(self, binary_path: str, workers: int = DEFAULT_WORKERS):
        self.binary_path = binary_path
        self.size = max(1, min(int(workers), MAX_WORKERS))
        self.workers: list[MihomoWorker] = []

    async def start(self) -> bool:
        """启动全部 worker，任一失败则整体回收并返回 False（调用方回退串行）"""
        try:
            for _ in range(self.size):
                w = MihomoWorker(self.binary_path)
                self.workers.append(w)  # 先登记，启动失败也能被 stop() 回收
                if not await w.start():
                    raise RuntimeError("worker 启动超时")
        except Exception as e:
            logger.error(f"并行池启动失败: {e}")
            await self.stop()
            return False
        return bool(self.workers)

    async def stop(self):
        for w in self.workers:
            try:
                await w.stop()
            except Exception:
                pass
        self.workers.clear()

__all__ = ['tcp_ping', 'tcp_ping_retry', 'run_tcp_ping', 'run_tcp_probe_pool', 'MihomoEngine', '_build_config_dict', '_wait_auto_selected', 'MihomoWorker', 'MihomoWorkerPool']
