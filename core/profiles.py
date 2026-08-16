#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点档案库（v4.29.0）：跨 run 的节点身份 / 生命周期 / 稳定性统计

数据存 output/profiles.json（本机私有，不进发布 zip，与 代理.txt 同级待遇）：
- version 固定 1；文件缺失/损坏/版本不符 → 扫描 output/测速结果_*.json 重放重建
- runs  最近 RUNS_MAX 条 run 索引（对比/分组选单用）
- nodes 节点档案（key=自增数字 id）

身份识别（append_run 时，按序）：
1. name 精确命中 → 2. name 剥去 _N 去重后缀命中 → 3. (type,server,port) 命中
4. 本轮桥接：与某已匹配节点 server:port 相同且落地 IP 相同 → 并入
5. 未命中 → 新建档案（addr 记首见身份）
桥接只发生在本轮内部，跨 run 不做（宁可多建档不误合）。

证据：每档案保留 EVIDENCE_MAX 条（最老在前），更早折叠进 fold 聚合；
加权统计 w = 0.5^(年龄/3)，quick 证据额外 x0.5；fold 按最老证据时间戳计权重。
只存聚合值，speed_per_sec 明细留在原结果 JSON；指标即时计算不落盘（改公式免迁移）。
"""
import json
import os
import re
import time

from .config import *
from .logging_setup import *
from .models import ProxyNode
from .utils import *

PROFILES_FILE = os.path.join(OUTPUT_DIR, "profiles.json")
PROFILES_VERSION = 1

# 档案内 appear 保留的最近出现次数上限（>= stability_window 最大档 20）
APPEAR_MAX = 20

_NAME_STRIP_RE = re.compile(r"_\d+$")  # 去重后缀 _2/_3（_dedupe_nodes 生成）


def _empty_data() -> dict:
    """空档案骨架"""
    return {"version": PROFILES_VERSION, "updated": "", "runs": [], "nodes": {},
            "next_id": 1}


def _addr_key(node) -> str:
    """身份三元组 (type,server,port) 串"""
    return f"{node.type}|{node.server}|{node.port}"


def _entry_key(node) -> tuple:
    """桥接用入口键 (server, port)"""
    return (node.server, node.port)


def _quality_of(mode: str) -> str:
    """模式 → 证据质量：standard（8s 窗口串行）/ quick（并行近似）/ streaming（纯解锁）"""
    if mode == "quick":
        return "quick"
    if mode == "streaming":
        return "streaming"
    return "standard"


def load_profiles() -> dict:
    """读取档案；文件缺失返回空骨架，损坏/版本不符自动重建（不抛异常）"""
    try:
        if not os.path.isfile(PROFILES_FILE):
            return _empty_data()
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != PROFILES_VERSION:
            raise ValueError("profiles version mismatch")
        if not isinstance(data.get("nodes"), dict) or not isinstance(data.get("runs"), list):
            raise ValueError("profiles structure invalid")
        data.setdefault("next_id", _next_id_hint(data))
        return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning("节点档案损坏或版本不符（%s），自动重建", _safe_exc_str(e),
                       extra=_ev("profiles_rebuild", {"reason": type(e).__name__}))
        return rebuild_profiles()


def _next_id_hint(data: dict) -> int:
    """从现有 id 推算 next_id（防御手改文件）"""
    ids = []
    for k in data.get("nodes", {}):
        try:
            ids.append(int(k))
        except (TypeError, ValueError):
            pass
    return (max(ids) + 1) if ids else 1


def save_profiles(data: dict) -> None:
    """原子写：tmp → os.replace"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tmp = PROFILES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROFILES_FILE)


def _report_files() -> list:
    """output/ 下全部结果 JSON（不含 profiles.json），按修改时间旧→新"""
    if not os.path.isdir(OUTPUT_DIR):
        return []
    out = []
    for f in os.listdir(OUTPUT_DIR):
        if f.startswith("测速结果_") and f.endswith(".json"):
            out.append(os.path.join(OUTPUT_DIR, f))
    out.sort(key=lambda p: os.path.getmtime(p))
    return out


def _run_id_from_filename(name: str) -> str:
    """文件名 → run_id（时间戳段，含毫秒后缀）"""
    m = re.search(r"_(\d{8}_\d{6}(?:_\d+)?)\.json$", name)
    return m.group(1) if m else ""


def rebuild_profiles() -> dict:
    """扫描 output/测速结果_*.json 逐个重放证据，重建档案与 runs（2-5 秒级）

    结果 JSON 也被删光 → 从空开始不报错。任何单文件异常跳过继续。
    """
    data = _empty_data()
    replayed = 0
    for fp in _report_files():
        try:
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            results = d.get("results") or []
            mode = d.get("mode") or "basic"
            ts = d.get("export_time") or time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fp)))
            quality = _quality_of(mode)
            run_id = _run_id_from_filename(os.path.basename(fp))
            ctx: dict = {}
            for entry in results:
                node = ProxyNode(
                    name=entry.get("name") or "?",
                    type=entry.get("type") or "ss",
                    server=entry.get("server") or "",
                    port=int(entry.get("port") or 0),
                )
                if not node.server:
                    continue
                nid = match_or_create(data, node, (entry.get("ip_info") or {}).get("ip") or "",
                                      ctx, first_seen=ts)
                p = data["nodes"][nid]
                ev = _evidence_from_json(entry, quality, ts, mode)
                _append_evidence(p, ev)
                _trim_evidence(p)
                p["appear"].append(ts)
                if len(p["appear"]) > APPEAR_MAX:
                    del p["appear"][:len(p["appear"]) - APPEAR_MAX]
            data["runs"].append({
                "run_id": run_id,
                "ts": ts,
                "mode": mode,
                "json_file": os.path.basename(fp),
                "node_count": len(results),
            })
            replayed += 1
        except Exception as e:
            logger.warning("重放 %s 失败，跳过: %s", os.path.basename(fp), _safe_exc_str(e))
    if len(data["runs"]) > RUNS_MAX:
        del data["runs"][:len(data["runs"]) - RUNS_MAX]
    data["next_id"] = _next_id_hint(data)
    logger.info("节点档案重建完成: %d 份结果 → %d 个节点",
                replayed, len(data["nodes"]),
                extra=_ev("profiles_rebuild", {"reason": "manual/repair",
                                               "runs": replayed,
                                               "nodes": len(data["nodes"])}))
    return data


def _evidence_from_json(entry: dict, quality: str, ts: str, mode: str) -> dict:
    """结果 JSON 单节点 → 证据（与 _build_evidence 同口径，只写实测维度）"""
    ev = {"ts": ts, "mode": mode, "quality": quality}
    if entry.get("speed_mbs") is not None:
        ev["speed"] = round(float(entry["speed_mbs"]), 2)
        ev["max_speed"] = round(float(entry.get("max_speed_mbs") or entry["speed_mbs"]), 2)
    if entry.get("tcp_ping_ms") is not None:
        ev["tcp_ping"] = round(float(entry["tcp_ping_ms"]), 1)
    if entry.get("tcp_probe") is not None:
        ev["tcp_probe"] = bool(entry["tcp_probe"])
    stream = entry.get("streaming") or {}
    vals = [v for v in stream.values()
            if isinstance(v, str) and not v.startswith("跳过")]
    if vals:
        ev["unlock"] = sum(1 for v in vals if ("解锁" in v or "可用" in v or "成功" in v))
        ev["unlock_total"] = len(vals)
    risk = (entry.get("ip_info") or {}).get("risk_score")
    if risk is not None:
        ev["risk"] = int(risk)
    if entry.get("sub_index") is not None:
        ev["sub_index"] = int(entry["sub_index"])
    return ev


def match_or_create(data: dict, node, ip: str = "", ctx: dict = None,
                    first_seen: str = "") -> str:
    """身份识别：按序匹配 by_name/去重后缀/by_addr/本轮桥接，未命中新建档案

    ctx 为本轮上下文 {"entry": {(server,port): (nid, ip)}}，供桥接判断；
    传 None 时跳过桥接（历史匹配仍可用）。first_seen 用于重放时写首见时间。
    """
    ctx = ctx or {}
    nid = None
    # 1. name 精确
    for pid, p in data["nodes"].items():
        if node.name in p.get("names", []):
            nid = pid
            break
    # 2. name 剥去 _N 去重后缀
    if nid is None:
        base = _NAME_STRIP_RE.sub("", node.name)
        for pid, p in data["nodes"].items():
            if base and base in p.get("names", []):
                nid = pid
                break
    # 3. (type, server, port)
    if nid is None:
        addr = _addr_key(node)
        for pid, p in data["nodes"].items():
            if p.get("addr") == addr:
                nid = pid
                break
    # 4. 本轮桥接：同入口同落地 = 同一条线路
    if nid is None and ip and isinstance(ctx.get("entry"), dict):
        hit = ctx["entry"].get(_entry_key(node))
        if hit and hit[1] == ip:
            nid = hit[0]
    # 5. 新建
    if nid is None:
        nid = str(data.get("next_id", 1))
        data["next_id"] = int(nid) + 1
        data["nodes"][nid] = {
            "names": [node.name],
            "addr": _addr_key(node),
            "subs": [],
            "first_seen": first_seen or time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": "",
            "seen_count": 0,
            "evidence": [],
            "fold": {"n": 0, "speed_sum": 0.0, "speed_ss": 0.0,
                     "reach_n": 0, "unlock_sum": 0, "ts": ""},
            "appear": [],
        }
    return nid


def _build_evidence(r, quality: str, ts: str, display_mode: str,
                    sub_index=None) -> dict:
    """TestResult → 证据（只写本模式实际测过的维度，缺的字段不写不填 0）"""
    ev = {"ts": ts, "mode": display_mode, "quality": quality}
    if r.speed is not None:
        ev["speed"] = round(float(r.speed), 2)
        ev["max_speed"] = round(float(r.max_speed or r.speed), 2)
    if r.tcp_ping is not None:
        ev["tcp_ping"] = round(float(r.tcp_ping), 1)
    if r.tcp_probe is not None:
        ev["tcp_probe"] = bool(r.tcp_probe)
    vals = [v for v in r.streaming.values()
            if isinstance(v, str) and not v.startswith("跳过")]
    if vals:
        ev["unlock"] = sum(1 for v in vals if ("解锁" in v or "可用" in v or "成功" in v))
        ev["unlock_total"] = len(vals)
    risk = (r.ip_info or {}).get("risk_score")
    if risk is not None:
        ev["risk"] = int(risk)
    if sub_index is not None:
        ev["sub_index"] = int(sub_index)
    return ev


def _append_evidence(p: dict, ev: dict) -> None:
    """追加证据 + 维护身份元数据（names/subs/seen_count/last_seen）"""
    p["evidence"].append(ev)
    p["last_seen"] = ev.get("ts") or p["last_seen"]
    p["seen_count"] = p.get("seen_count", 0) + 1


def _trim_evidence(p: dict) -> None:
    """evidence 超过 EVIDENCE_MAX → 最老移入 fold 聚合"""
    evs = p["evidence"]
    if len(evs) <= EVIDENCE_MAX:
        return
    fold = p.setdefault("fold", {"n": 0, "speed_sum": 0.0, "speed_ss": 0.0,
                                 "reach_n": 0, "unlock_sum": 0, "ts": ""})
    moved = evs[:len(evs) - EVIDENCE_MAX]
    for e in moved:
        fold["n"] += 1
        if e.get("speed") is not None:
            fold["speed_sum"] += e["speed"]
            fold["speed_ss"] += e["speed"] ** 2
        if e.get("tcp_ping") is not None or e.get("tcp_probe") is True:
            fold["reach_n"] += 1
        if e.get("unlock") is not None:
            fold["unlock_sum"] += e["unlock"]
        fold["ts"] = e.get("ts") or fold["ts"]  # 折叠块最老时间戳（权重用）
    del evs[:len(evs) - EVIDENCE_MAX]


def append_run(results: list, mode: str, display_mode: str, report_ts: str,
               json_file: str = "") -> None:
    """run 收尾归档：识别身份 → 证据追加/折叠 → runs 追加裁剪 → 原子写

    任何异常 WARNING 一条日志静默降级（不影响已产出的报告）。
    """
    try:
        data = load_profiles()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        quality = _quality_of(mode)
        ctx: dict = {}
        for r in results:
            nid = match_or_create(data, r.node, (r.ip_info or {}).get("ip") or "", ctx)
            # 注册本轮入口→(档案, 落地IP)，供后续节点桥接
            ctx.setdefault("entry", {})
            ctx["entry"].setdefault(_entry_key(r.node), (nid, (r.ip_info or {}).get("ip") or ""))
            p = data["nodes"][nid]
            if r.node.name not in p["names"]:
                p["names"].append(r.node.name)  # 改名追踪（含去重后缀名，保留原样）
            if r.node.sub_index is not None and r.node.sub_index not in p.get("subs", []):
                p.setdefault("subs", []).append(r.node.sub_index)
            ev = _build_evidence(r, quality, ts, display_mode, r.node.sub_index)
            _append_evidence(p, ev)
            _trim_evidence(p)
            p["appear"].append(ts)
            if len(p["appear"]) > APPEAR_MAX:
                del p["appear"][:len(p["appear"]) - APPEAR_MAX]
        if json_file:
            data["runs"].append({
                "run_id": report_ts,
                "ts": ts,
                "mode": display_mode,
                "json_file": os.path.basename(json_file),
                "node_count": len(results),
            })
            if len(data["runs"]) > RUNS_MAX:
                del data["runs"][:len(data["runs"]) - RUNS_MAX]
        data["updated"] = ts
        save_profiles(data)
        logger.info("节点档案已更新: %d 个节点证据归档",
                    len(results),
                    extra=_ev("profiles_written", {"nodes": len(results),
                                                   "run_id": report_ts}))
    except Exception as e:
        logger.warning("节点档案写入失败（不影响报告）: %s", _safe_exc_str(e))


def _weighted_stats(p: dict):
    """档案加权统计：平均速度 / 波动σ / 可达率（w = 0.5^(年龄/3)，quick x0.5）

    返回 dict: avg_speed, sigma, reach_rate（无数据时 None）
    """
    evs = p["evidence"]
    ev_n = len(evs)
    items = []  # (age, quick_flag, speed, reach)
    for i, e in enumerate(evs):
        age = ev_n - 1 - i
        reach = None
        if e.get("tcp_ping") is not None or e.get("tcp_probe") is not None:
            reach = 1 if (e.get("tcp_ping") is not None or e.get("tcp_probe") is True) else 0
        items.append((age, e.get("quality") == "quick", e.get("speed"), reach))
    fold = p.get("fold") or {}
    fold_n = fold.get("n") or 0
    age_fold = ev_n + fold_n - 1  # 折叠块按最老时间戳计年龄（无折叠时为占位值）
    # 速度统计（evidence 逐条 + fold 按最老时间戳整体加权）
    w_s = w_ss = w_t = 0.0
    for age, quick, speed, _ in items:
        if speed is None:
            continue
        w = 0.5 ** (age / 3.0) * (0.5 if quick else 1.0)
        w_s += w * speed
        w_ss += w * speed * speed
        w_t += w
    if fold_n:
        wf = 0.5 ** (age_fold / 3.0)
        w_s += fold["speed_sum"] * wf
        w_ss += fold["speed_ss"] * wf
        w_t += fold_n * wf
    avg = (w_s / w_t) if w_t > 0 else None
    sigma = None
    if avg is not None and w_t > 0:
        var = max(0.0, w_ss / w_t - avg * avg)
        sigma = var ** 0.5
    # 可达率
    rw = rr = 0.0
    for age, quick, _, reach in items:
        if reach is None:
            continue
        w = 0.5 ** (age / 3.0) * (0.5 if quick else 1.0)
        rw += w
        rr += w * reach
    if fold_n:
        wf = 0.5 ** (age_fold / 3.0)
        rw += fold_n * wf
        rr += fold["reach_n"] * wf
    reach_rate = (rr / rw) if rw > 0 else None
    return {"avg_speed": avg, "sigma": sigma, "reach_rate": reach_rate}


def _appear_ratio(p: dict, last_run_ts: list) -> float:
    """近 N 次 run 出现率（appear 列表与 runs 时间戳对齐）"""
    if not last_run_ts:
        return 0.0
    hit = sum(1 for ts in p.get("appear", []) if ts in last_run_ts)
    return hit / len(last_run_ts)


def node_stability_report(data: dict, window: int = 10) -> list:
    """稳定性视图：每档案一行（常青树/过山车/新面孔/普通 分层）

    window 为出现率口径的近 N 次 run 数。返回按平均速度降序的行列表：
    [{name, layer, appear, appear_total, reach, avg, sigma, evidence_n}]
    """
    runs = data.get("runs") or []
    win = max(1, min(int(window), len(runs))) if runs else 1
    last_ts = [r["ts"] for r in runs[-win:]]
    rows = []
    for pid, p in data["nodes"].items():
        stats = _weighted_stats(p)
        ev_n = len(p.get("evidence", [])) + (p.get("fold") or {}).get("n", 0)
        appear_ratio = _appear_ratio(p, last_ts) if runs else 0.0
        avg = stats["avg_speed"]
        sigma = stats["sigma"]
        if ev_n < NEW_FACE_MIN_EVIDENCE:
            layer = "新面孔"
        elif appear_ratio >= STABILITY_APPEAR_RATIO and avg is not None:
            layer = "常青树" if (sigma is None or sigma < STABILITY_SIGMA * avg) else "过山车"
        else:
            layer = "普通"
        rows.append({
            "name": (p.get("names") or ["?"])[-1],
            "layer": layer,
            "appear": round(appear_ratio * len(last_ts)) if runs else 0,
            "appear_total": len(last_ts),
            "reach": stats["reach_rate"],
            "avg": avg,
            "sigma": sigma,
            "evidence_n": ev_n,
        })
    rows.sort(key=lambda x: (x["avg"] is None, -(x["avg"] or 0)))
    return rows


__all__ = ['PROFILES_FILE', 'load_profiles', 'save_profiles', 'rebuild_profiles',
           'append_run', 'match_or_create', 'node_stability_report']
