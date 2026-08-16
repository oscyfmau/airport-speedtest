#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志系统：控制台文本 + 文件 JSONL 双输出、异常钩子、日志轮换"""
import json
import logging
import os
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime

from .config import *
from .utils import *

logger = logging.getLogger("speed_test")


_LOG_FILE = ""


_LOG_HANDLER = None


def _cleanup_stale_configs():
    """清理历史运行（异常退出）残留的临时配置文件（只删超过 2 小时的，避免误删并发实例配置；
    v4.35.0：残留窗口 6h→2h，减少含节点凭据的临时 yaml 在 %TEMP% 的存留时长）"""
    try:
        tmp = tempfile.gettempdir()
        now = time.time()
        for f in os.listdir(tmp):
            if (f.startswith("mihomo_") or f.startswith("mihomo_worker_")) and f.endswith(".yaml"):
                try:
                    p = os.path.join(tmp, f)
                    if now - os.path.getmtime(p) > 2 * 3600:
                        os.remove(p)
                except OSError:
                    pass
    except Exception:
        pass


def setup_logging() -> str:
    """初始化日志：控制台 INFO（文本）+ 文件 JSONL（log/测速日志_*.jsonl，每次 bat 运行一个独立文件、全部保留），返回日志文件路径"""
    global _LOG_FILE, _LOG_HANDLER
    _cleanup_stale_configs()
    logger.setLevel(logging.DEBUG)

    if logger.handlers:  # 已初始化：移除旧 handler，避免重复输出
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    # v4.18.0：级别固定 8 显示宽（INFO/WARNING/ERROR），消息列对齐
    ch.setFormatter(_ConsoleFormatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)

    _install_excepthook()
    return new_run_log()


# 交互事件迁移（v4.20.0 起不再调用：每次 bat 运行一个独立文件、不删除旧日志，无需迁移；函数保留接口）
_INTERACT_EVENTS = {"menu_choice", "invalid_input", "manual_subscribe_input",
                    "subscribe_select"}


def _migrate_interact_lines(old_path: str, new_path: str) -> None:
    """把旧日志中的交互事件行（菜单选择等）追加到新日志开头（v4.20.0 起未调用，保留兼容）"""
    try:
        keep = []
        with open(old_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line).get("event", "")
                except Exception:
                    continue
                if ev in _INTERACT_EVENTS:
                    keep.append(line)
        if keep:
            with open(new_path, "a", encoding="utf-8") as f:
                f.write("\n".join(keep) + "\n")
    except Exception:
        pass


def new_run_log() -> str:
    """新建 JSONL 日志文件（v4.20.0 起：每次 bat 运行一个独立文件；不再删除旧日志、不再迁移交互事件，log/ 保留全部历史）"""
    global _LOG_FILE, _LOG_HANDLER
    if _LOG_HANDLER is not None:
        logger.removeHandler(_LOG_HANDLER)
        _LOG_HANDLER.close()
    os.makedirs(LOG_DIR, exist_ok=True)
    base = time.strftime("测速日志_%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, base + ".jsonl")
    if os.path.exists(path):  # 同一秒内多次运行：加后缀避免同名
        path = os.path.join(LOG_DIR, base + f"_{int(time.monotonic() * 1000) % 1000:03d}.jsonl")
    _LOG_FILE = path
    _LOG_HANDLER = JsonlFileHandler(path)
    logger.addHandler(_LOG_HANDLER)
    return _LOG_FILE


class JsonlFileHandler(logging.Handler):
    """JSONL 文件日志：每行一个 JSON 对象，逐条 flush（强杀/关窗口也不丢已写内容）"""

    def __init__(self, path: str, level=logging.DEBUG):
        super().__init__(level)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")
        self._lock = threading.Lock()  # v4.39.0：串行化写入（当前单线程模型无实际并发，防御性）

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "event": getattr(record, "event", "") or "",
                "msg": record.getMessage(),
            }
            data = getattr(record, "data", None)
            if data is not None:
                entry["data"] = data
            if record.exc_info and record.exc_info[0]:
                entry["exc"] = _safe_exc_str(
                    "".join(traceback.format_exception(*record.exc_info)).strip())
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
            with self._lock:  # v4.39.0：写+flush 原子化
                self._fh.write(_sanitize_surrogates(line))
                self._fh.flush()
        except Exception as e:
            # 写日志失败不能拖垮主流程；首次失败向 stderr 提示一次，避免静默丢失
            if not getattr(self, "_warned", False):
                self._warned = True
                try:
                    print(f"[日志写入失败] {self.path}: {e}", file=sys.stderr)
                except Exception:
                    pass

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
        super().close()


def _ev(event: str, data=None) -> dict:
    """构造 logger extra：结构化事件名 + 数据（JSONL 文件日志用，控制台忽略）"""
    return {"event": event, "data": data}


def _pkg_version(name: str) -> str:
    """读取已安装包版本（失败返回 ?）"""
    try:
        import importlib.metadata as _im
        return _im.version(name)
    except Exception:
        return "?"


def _cleanup_empty_log() -> None:
    """进程退出时：仅删除零字节的空日志文件（v4.39.0 修正 docstring——只删空文件；
    --help/--report 等未产生任何记录的场景；菜单退出会写 menu_choice 行，文件非空保留，
    与"日志全部保留"策略一致）"""
    global _LOG_HANDLER, _LOG_FILE
    if _LOG_HANDLER is not None:
        try:
            logger.removeHandler(_LOG_HANDLER)
            _LOG_HANDLER.close()
        except Exception:
            pass
        _LOG_HANDLER = None
    try:
        if _LOG_FILE and os.path.isfile(_LOG_FILE) and os.path.getsize(_LOG_FILE) == 0:
            os.remove(_LOG_FILE)
    except OSError:
        pass


_EXCEPTHOOK_INSTALLED = False


def _install_excepthook() -> None:
    """全局未捕获异常兜底：完整 traceback 写入 JSONL 日志（乱操作也不丢现场），并链式调用既有 hook

    v4.27.0：模块级标记只装一次——setup_logging 多次调用不再链式叠加钩子
    （旧实现每次调用都包一层，同进程内异常被重复写日志）
    """
    global _EXCEPTHOOK_INSTALLED
    if _EXCEPTHOOK_INSTALLED:
        return
    _EXCEPTHOOK_INSTALLED = True
    _old_hook = sys.excepthook

    def _hook(tp, val, tb):
        text = _safe_exc_str("".join(traceback.format_exception(tp, val, tb)).strip())
        try:
            logger.critical("未捕获异常: %s", text,
                            extra=_ev("uncaught_exception", {"traceback": text}))
        except Exception:
            pass
        try:
            _old_hook(tp, val, tb)
        except Exception:
            pass
    sys.excepthook = _hook


class _ConsoleFormatter(logging.Formatter):
    """仅控制台格式化器：整行套用 _flag_to_text（国旗 emoji 转 [XX]）。

    文件日志用普通 Formatter，保留原始节点名。
    """

    def format(self, record):
        return _sanitize_surrogates(_flag_to_text(super().format(record)))

__all__ = ['logger', '_LOG_FILE', '_LOG_HANDLER', '_cleanup_stale_configs', 'setup_logging', 'new_run_log', 'JsonlFileHandler', '_ev', '_pkg_version', '_cleanup_empty_log', '_install_excepthook', '_ConsoleFormatter']
