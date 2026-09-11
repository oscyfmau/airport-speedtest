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
from datetime import datetime

from .config import *
from .logging_setup import *
from .models import ProxyNode
from .utils import *

PROFILES_FILE = os.path.join(OUTPUT_DIR, "profiles.json")
PROFILES_VERSION = 1

# 档案内 appear 保留的最近出现次数上限（>= stability_window 最大档 20）
APPEAR_MAX = 20

_NAME_STRIP_RE = re.compile(r"_\d+$")  # 去重后缀 _2/_3（_dedupe_nodes 生成）

# v4.43.0 修复：流媒体结果值里属于"没测成"的前缀——不计入解锁率分母，
# 解锁判定也先排除它们（旧实现 `"可用" in v` 把 "失败(区域不可用)" 算成了解锁）
_UNDETECTED_PREFIXES = ("跳过", "错误")
_NEGATIVE_PREFIXES = ("失败", "错误", "跳过", "未知", "封锁")


def _countable_streaming(v) -> bool:
    """该流媒体值是否算"实际检测过"（跳过/错误不计入分母，坏节点不稀释解锁率）"""
    return isinstance(v, str) and not v.startswith(_UNDETECTED_PREFIXES)


def _is_unlocked(v) -> bool:
    """解锁判定（三处统一口径）：排除 失败/错误/跳过 等前缀后，再看 解锁/可用/成功

    旧实现用子串 `"可用" in v`，会把 "失败(区域不可用)"（Disney/Max 文案）
    误判成解锁；且 `"不可用"` 也含 `"可用"` 子串。
    """
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s or s.startswith(_NEGATIVE_PREFIXES) or "不可用" in s:
        return False
    return ("解锁" in s) or ("可用" in s) or ("成功" in s)


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
            seen_nids: set = set()  # 同轮重复映射同一档案时只归档一次（与 append_run 同口径）
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
                if nid in seen_nids:
                    continue  # 证据/出现次数每轮每档案只记一次
                seen_nids.add(nid)
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
    vals = [v for v in stream.values() if _countable_streaming(v)]
    if vals:
        ev["unlock"] = sum(1 for v in vals if _is_unlocked(v))
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
            # fold 计数（v4.43.0 修复）：speed_n=带速度维度的折叠条数、
            # reach_total=带可达判定的折叠条数，作为 _weighted_stats 的分母
            "fold": {"n": 0, "speed_sum": 0.0, "speed_ss": 0.0, "speed_n": 0,
                     "reach_n": 0, "reach_total": 0, "unlock_sum": 0, "ts": ""},
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
    vals = [v for v in r.streaming.values() if _countable_streaming(v)]
    if vals:
        ev["unlock"] = sum(1 for v in vals if _is_unlocked(v))
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
    fold = p.setdefault("fold", {"n": 0, "speed_sum": 0.0, "speed_ss": 0.0, "speed_n": 0,
                                 "reach_n": 0, "reach_total": 0, "unlock_sum": 0, "ts": ""})
    moved = evs[:len(evs) - EVIDENCE_MAX]
    for e in moved:
        fold["n"] += 1
        if e.get("speed") is not None:
            fold["speed_sum"] += e["speed"]
            fold["speed_ss"] += e["speed"] ** 2
            # 只有带速度维度的折叠条目才进平均速度分母（旧实现用 fold["n"] → 系统性压低均值）
            fold["speed_n"] = fold.get("speed_n", 0) + 1
        if e.get("tcp_ping") is not None or e.get("tcp_probe") is not None:
            # 有可达判定（含 tcp_probe=False 的"不可达"）才进可达率分母，与逐条路径同口径
            fold["reach_total"] = fold.get("reach_total", 0) + 1
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
        # v4.43.0 修复：同轮多节点可能映射到同一档案（入口相同/桥接），
        # evidence/appear 每档案每轮只记一次，否则出现率可 >100%、证据条数虚高
        seen_nids: set = set()
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
            if nid in seen_nids:
                continue  # 身份元数据已合并，证据/出现次数不重复记
            seen_nids.add(nid)
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
        # 分母只算"带速度维度"的折叠条数（旧档案无 speed_n → 退回 fold_n 保持兼容）
        w_t += fold.get("speed_n", fold_n) * wf
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
        # 分母只算"带可达判定"的折叠条数（旧档案无 reach_total → 退回 fold_n 保持兼容）
        rw += fold.get("reach_total", fold_n) * wf
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


def _is_peak_hour(ts: str) -> bool:
    """晚高峰标注（v4.30.0）：18-23 点或周末（周六/周日）"""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False
    return dt.hour >= 18 or dt.weekday() >= 5


def _load_run_json(json_file: str):
    """读取结果 JSON 内容（缺失/损坏返回 None，调用方降级到档案 evidence）"""
    if not json_file:
        return None
    try:
        with open(os.path.join(OUTPUT_DIR, json_file), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _archive_entries_for_run(data: dict, run_ts: str) -> list:
    """档案降级数据源：取 ts 匹配该 run 的证据条目（含节点名与 addr）"""
    out = []
    for pid, p in data["nodes"].items():
        for e in p.get("evidence", []):
            if e.get("ts") == run_ts:
                out.append({"name": (p.get("names") or ["?"])[-1],
                            "addr": p.get("addr", ""), **e})
                break
    return out


def _entry_identity(e: dict) -> tuple:
    """对齐键：name 精确 / 剥 _N 后缀 / (type,server,port)"""
    name = e.get("name") or ""
    addr = e.get("addr") or f"{e.get('type')}|{e.get('server')}|{e.get('port')}"
    return name, _NAME_STRIP_RE.sub("", name), addr


def _align_entries(list_a: list, list_b: list) -> tuple:
    """两 run 节点对齐（复用档案匹配三级：name → 剥后缀 → (type,server,port)）

    返回 (pairs[(a,b)], only_a, only_b)
    """
    pairs = []
    used_b = set()
    b_by_name = {}
    b_by_strip = {}
    b_by_addr = {}
    for i, b in enumerate(list_b):
        name, strip, addr = _entry_identity(b)
        b_by_name.setdefault(name, []).append(i)
        if strip:
            b_by_strip.setdefault(strip, []).append(i)
        b_by_addr.setdefault(addr, []).append(i)
    for a in list_a:
        name, strip, addr = _entry_identity(a)
        idx = None
        for pool in (b_by_name.get(name), b_by_strip.get(strip), b_by_addr.get(addr)):
            if pool:
                idx = next((i for i in pool if i not in used_b), None)
                if idx is not None:
                    break
        if idx is not None:
            used_b.add(idx)
            pairs.append((a, list_b[idx]))
        else:
            pairs.append((a, None))
    only_b = [b for i, b in enumerate(list_b) if i not in used_b]
    return pairs, only_b


def _speed_of(e: dict):
    return e.get("speed_mbs") if e.get("speed_mbs") is not None else e.get("speed")


def run_compare_report(data: dict, run_a_id: str, run_b_id: str) -> dict:
    """结果对比（v4.30.0，二级菜单 2）：两次 run 节点对齐 + 差分

    数据源：原始 JSON 优先，缺失降级档案 evidence（无组内排名）。
    返回 {"runs": (meta_a, meta_b), "note": 晚高峰提示, "rows": [...], "only_a": n, "only_b": n}
    """
    runs = data.get("runs") or []
    ra = next((r for r in runs if r["run_id"] == run_a_id), None)
    rb = next((r for r in runs if r["run_id"] == run_b_id), None)
    if not ra or not rb:
        return {"error": "所选测试不在档案索引中"}
    ja = _load_run_json(ra.get("json_file"))
    jb = _load_run_json(rb.get("json_file"))
    if ja and ja.get("results"):
        list_a = ja["results"]
        ranked_a = sorted(list_a, key=lambda e: (_speed_of(e) is None, -(_speed_of(e) or 0)))
        rank_a = {id(e): i + 1 for i, e in enumerate(ranked_a)}
    else:
        list_a = _archive_entries_for_run(data, ra["ts"])
        rank_a = {}
    if jb and jb.get("results"):
        list_b = jb["results"]
        ranked_b = sorted(list_b, key=lambda e: (_speed_of(e) is None, -(_speed_of(e) or 0)))
        rank_b = {id(e): i + 1 for i, e in enumerate(ranked_b)}
    else:
        list_b = _archive_entries_for_run(data, rb["ts"])
        rank_b = {}

    pairs, only_b = _align_entries(list_a, list_b)
    only_a = sum(1 for a, b in pairs if b is None)
    rows = []
    for a, b in pairs:
        sa = _speed_of(a) if a else None
        sb = _speed_of(b) if b else None
        name = (a or b).get("name")
        pa = a.get("tcp_ping_ms") if a and a.get("tcp_ping_ms") is not None else (
            a.get("tcp_ping") if a else None)
        pb = b.get("tcp_ping_ms") if b and b.get("tcp_ping_ms") is not None else (
            b.get("tcp_ping") if b else None)
        ua = a.get("unlock") if a else None
        ub = b.get("unlock") if b else None
        ra_rank = rank_a.get(id(a)) if a else None
        rb_rank = rank_b.get(id(b)) if b else None
        if sa is not None and sb is not None and sa > 0:
            delta = (sb - sa) / sa * 100
            d_txt = f"{delta:+.0f}%" + ("↑" if delta > 20 else "↓" if delta < -20 else "")
        else:
            delta = None
            d_txt = "新/缺" if (sa is None) != (sb is None) else "--"
        rows.append({
            "name": name,
            "speed_a": sa, "speed_b": sb, "delta_txt": d_txt,
            "lat_a": pa, "lat_b": pb,
            "unlock_a": ua, "unlock_b": ub,
            "rank_a": ra_rank, "rank_b": rb_rank,
        })
    note = ""
    if _is_peak_hour(ra["ts"]) != _is_peak_hour(rb["ts"]):
        note = "晚高峰对比：两轮中恰有一轮处于晚高峰/周末，速度差分含时段因素"
    return {"runs": (ra, rb), "note": note, "rows": rows,
            "only_a": only_a, "only_b": len(only_b)}


def subscription_group_report(data: dict, run_id: str = "") -> dict:
    """订阅分组对比（v4.31.0，二级菜单 3）：按节点 sub_index 分组的横评

    数据源 = 所选 run 的原始 JSON（缺省最近一次）。解锁率口径：
    实际检测的服务中"解锁/可用"计数 ÷ 检测数（排除"跳过/错误"，坏节点不稀释）。
    返回 {"run": meta, "rows": [...], "note": 提示}
    """
    runs = data.get("runs") or []
    run = (next((r for r in runs if r["run_id"] == run_id), None) if run_id
           else (runs[-1] if runs else None))
    if not run:
        return {"error": "档案中没有测试记录"}
    j = _load_run_json(run.get("json_file"))
    if not j or not j.get("results"):
        return {"error": "该次测试的原始 JSON 缺失，无法分组（可用节点稳定性视图替代）"}
    groups = {}
    for e in j["results"]:
        k = e.get("sub_index")
        if k is None:
            k = "未知"
        g = groups.setdefault(k, {"n": 0, "speeds": [], "max_speed": 0.0,
                                  "lats": [], "risks": [],
                                  "unlock": 0, "unlock_total": 0})
        g["n"] += 1
        s = e.get("speed_mbs")
        if s is not None:
            g["speeds"].append(s)
            g["max_speed"] = max(g["max_speed"], e.get("max_speed_mbs") or s)
        p = e.get("tcp_ping_ms")
        if p is not None:
            g["lats"].append(p)
        risk = (e.get("ip_info") or {}).get("risk_score")
        if risk is not None:
            g["risks"].append(risk)
        vals = [v for v in (e.get("streaming") or {}).values()
                if _countable_streaming(v)]
        g["unlock_total"] += len(vals)
        g["unlock"] += sum(1 for v in vals if _is_unlocked(v))
    rows = []
    for k, g in groups.items():
        rows.append({
            "group": k,
            "n": g["n"],
            "avg_speed": (sum(g["speeds"]) / len(g["speeds"])) if g["speeds"] else None,
            "max_speed": g["max_speed"] or None,
            "avg_lat": (sum(g["lats"]) / len(g["lats"])) if g["lats"] else None,
            "avg_risk": (sum(g["risks"]) / len(g["risks"])) if g["risks"] else None,
            "unlock": g["unlock"],
            "unlock_total": g["unlock_total"],
            "unlock_rate": (g["unlock"] / g["unlock_total"]) if g["unlock_total"] else None,
        })
    rows.sort(key=lambda x: (x["avg_speed"] is None, -(x["avg_speed"] or 0)))
    multi = any(isinstance(k, int) for k in groups) and len(groups) > 1
    note = ""
    if len(groups) <= 1:
        note = "只有 1 个订阅（或旧数据无 sub_index 分组字段）"
    return {"run": run, "rows": rows, "note": note}


def cleanup_outputs(keep_reports: int = KEEP_REPORTS_DEFAULT,
                    keep_logs_days: int = KEEP_LOGS_DAYS_DEFAULT,
                    dry_run: bool = False) -> dict:
    """产物累积清理（v4.31.0）：output/ 保留最近 keep_reports 份 PNG+JSON 配对、
    log/ 保留最近 keep_logs_days 天。

    护栏：只匹配 测速结果_* / 测速日志_* 前缀、按 basename 成对删、
    profiles.json 永不参与、单个文件异常跳过不中断。返回统计 dict。
    """
    reports_deleted = 0
    logs_deleted = 0
    freed = 0
    try:
        if os.path.isdir(OUTPUT_DIR):
            groups = {}
            for f in os.listdir(OUTPUT_DIR):
                if f.startswith("测速结果_") and (f.endswith(".png") or f.endswith(".json")):
                    groups.setdefault(os.path.splitext(f)[0], []).append(f)
            items = sorted(groups.items(),
                           key=lambda kv: os.path.getmtime(os.path.join(OUTPUT_DIR, kv[1][0])))
            victims = items[:-keep_reports] if len(items) > keep_reports else []
            for base, files in victims:
                for f in files:
                    p = os.path.join(OUTPUT_DIR, f)
                    try:
                        sz = os.path.getsize(p)
                        if not dry_run:
                            os.remove(p)
                        freed += sz
                    except OSError:
                        pass  # 单个文件异常跳过
                reports_deleted += 1
    except OSError:
        pass
    try:
        if os.path.isdir(LOG_DIR):
            cutoff = time.time() - max(1, int(keep_logs_days)) * 86400
            for f in os.listdir(LOG_DIR):
                if f.startswith("测速日志_") and f.endswith(".jsonl"):
                    p = os.path.join(LOG_DIR, f)
                    try:
                        if os.path.getmtime(p) < cutoff:
                            sz = os.path.getsize(p)
                            if not dry_run:
                                os.remove(p)
                            freed += sz
                            logs_deleted += 1
                    except OSError:
                        pass
    except OSError:
        pass
    return {"reports_deleted": reports_deleted, "logs_deleted": logs_deleted,
            "freed_bytes": freed}


__all__ = ['PROFILES_FILE', '_is_unlocked', '_countable_streaming',
           'load_profiles', 'save_profiles', 'rebuild_profiles',
           'append_run', 'match_or_create', 'node_stability_report',
           'run_compare_report', '_is_peak_hour', 'subscription_group_report',
           'cleanup_outputs']
