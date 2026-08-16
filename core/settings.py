#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户设置：跨会话持久化（~/.airport_speedtest.json，JSON 格式）

菜单 12 设置页读写；菜单模式运行测试时生效（窗口秒数/并行数/自动打开报告），
命令行直跑保持默认行为不受影响。文件缺失/损坏自动回退默认值，不报错。
"""
import json
import os

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".airport_speedtest.json")


DEFAULTS = {
    "speed_window_seconds": 8,  # 测速窗口秒数（3-30）
    "workers": 4,               # 流媒体/IP/网页并行数（1-8）
    "auto_open_report": True,   # 测试完成后自动打开 PNG 报告
    "stability_window": 10,     # 节点稳定性视图的近 N 次 run 窗口（5/10/20）
    "confirm_large_run": True,  # 节点数 > 50 时测前需回车确认（v4.29.0 流量预估）
}


_SETTINGS = None  # 进程内缓存（文件只在首次读取时加载）


def _clamp(data: dict) -> None:
    """钳制设置值到合法范围；非法类型回退默认（文件损坏自愈）"""
    try:
        data["speed_window_seconds"] = max(3, min(int(data.get("speed_window_seconds", 8)), 30))
    except (TypeError, ValueError):
        data["speed_window_seconds"] = DEFAULTS["speed_window_seconds"]
    try:
        data["workers"] = max(1, min(int(data.get("workers", 4)), 8))
    except (TypeError, ValueError):
        data["workers"] = DEFAULTS["workers"]
    # v4.27.0：字符串 "false"/"0" 不再被 bool("false")=True 误判为开启
    raw = data.get("auto_open_report", True)
    if isinstance(raw, str):
        raw = raw.strip().lower() in ("1", "true", "yes", "on")
    data["auto_open_report"] = bool(raw)
    # v4.29.0：稳定性窗口（5/10/20，其他值回退默认）
    try:
        sw = int(data.get("stability_window", 10))
        data["stability_window"] = sw if sw in (5, 10, 20) else DEFAULTS["stability_window"]
    except (TypeError, ValueError):
        data["stability_window"] = DEFAULTS["stability_window"]
    raw = data.get("confirm_large_run", True)
    if isinstance(raw, str):
        raw = raw.strip().lower() in ("1", "true", "yes", "on")
    data["confirm_large_run"] = bool(raw)


def load_settings() -> dict:
    """读取设置（带进程内缓存；文件缺失/损坏回退默认）"""
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS
    data = dict(DEFAULTS)
    try:
        if os.path.isfile(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k in DEFAULTS:
                    if k in raw:
                        data[k] = raw[k]
    except Exception:
        pass  # 损坏/权限问题：静默回退默认
    _clamp(data)
    _SETTINGS = data
    return _SETTINGS


def save_settings(data: dict) -> None:
    """保存设置（先钳制）并更新缓存"""
    _clamp(data)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    global _SETTINGS
    _SETTINGS = data


def reset_settings() -> dict:
    """恢复默认并保存"""
    data = dict(DEFAULTS)
    save_settings(data)
    return data


def update_settings(**kwargs) -> dict:
    """局部更新设置项并保存"""
    data = load_settings()
    data.update(kwargs)
    save_settings(data)
    return data


def invalidate_cache() -> None:
    """清空进程内缓存（下次读取重新加载文件）"""
    global _SETTINGS
    _SETTINGS = None

__all__ = ['SETTINGS_FILE', 'DEFAULTS', 'load_settings', 'save_settings',
           'reset_settings', 'update_settings', 'invalidate_cache']
