#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mihomo 子进程登记与统一兜底终止（atexit 同步兜底）"""
import subprocess

_ACTIVE_PROCS = []


def _track_proc(p) -> "subprocess.Popen":
    """登记 mihomo 子进程，进程退出时统一兜底终止"""
    _ACTIVE_PROCS.append(p)
    return p


def _untrack_proc(p) -> None:
    """进程正常回收后注销登记（防止菜单反复测试下列表无限增长）"""
    try:
        if p in _ACTIVE_PROCS:
            _ACTIVE_PROCS.remove(p)
    except Exception:
        pass


def _cleanup_procs() -> None:
    """同步兜底：terminate 全部未退出的登记进程（atexit 调用，无 await）"""
    for p in _ACTIVE_PROCS:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    for p in _ACTIVE_PROCS:
        try:
            if p.poll() is None:
                p.wait(timeout=3)
            else:
                p.wait(timeout=1)  # 已退出的进程补一次 wait，回收句柄/僵尸
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

__all__ = ['_ACTIVE_PROCS', '_track_proc', '_untrack_proc', '_cleanup_procs']
