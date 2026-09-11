#!/usr/bin/env python3
"""命令行入口：参数解析 / 交互菜单 / 内核更新"""
import asyncio
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .config import *
from .engine import *
from .logging_setup import *
from .parser import *
from .procs import *
from .profiles import *  # v4.29.0：节点档案库（节点稳定性菜单）
from .runner import *
from .settings import *
from .utils import *


def _open_report(path: str) -> bool:
    """打开报告文件（Windows os.startfile；macOS open；Linux xdg-open；失败不崩溃）

    v4.17.0：Windows 上 os.startfile 因系统无默认应用关联失败（WinError 1155）时，
    回退 `explorer /select` 打开所在目录并选中文件，保证报告可被找到。
    """
    try:
        if sys.platform == "win32":
            try:
                os.startfile(path)
            except OSError:
                subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception as e:
        logger.error("打开报告失败: %s (%s)", path, e)
        return False


_MODE_NAMES = {"speed": "简单测速", "basic": "简单测速", "normal": "标准测试",
               "full": "完整测速", "streaming": "流媒体", "streaming_ai": "AI流媒体",
               "streaming_all": "全部流媒体", "quick": "快速检测"}

# v4.29.0：文件名时间戳可能是秒级或带毫秒后缀（_mmm），剥掉尾部时间戳段取模式名
_MODE_TAIL_RE = re.compile(r"_\d{8}_\d{6}(?:_\d+)?$")


def _safe_mtime(path: str) -> float:
    """文件修改时间（取不到返回 0）

    v4.44.0：列表/取最新时用——文件在 listdir 之后被删掉或权限不足时
    os.path.getmtime 抛 OSError，会让整个菜单崩掉（同函数里紧邻的
    time.localtime(os.path.getmtime(...)) 本来就包了 try，这里补齐）。
    """
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _read_text_auto(path: str) -> tuple:
    """读文本文件，返回 (文本, 回写该用的编码)

    v4.44.0：先整体读字节，再依次尝试 utf-8-sig → gbk（与
    parser.read_subscribe_urls 一致）——中文 Windows 记事本默认 ANSI(GBK)
    保存的 代理.txt 才能读写。返回编码供写回用：原文带 BOM 保留 utf-8-sig
    （不丢 BOM），无 BOM 用 utf-8，GBK 文件仍按 GBK 写回、不悄悄改编码。
    """
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "gbk"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if enc == "utf-8-sig":
            return text, ("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
        return text, "gbk"
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _merge_urls(dst: list, src: list) -> list:
    """把 src 里的订阅 URL 追加进 dst（去重保序）

    v4.44.0：位置 URL 与 -i 文件内容统一走这里——旧实现是相互赋值覆盖，
    后出现的来源会把先收集到的 URL 静默丢掉。
    """
    seen = set(dst)
    for u in src:
        if u not in seen:
            seen.add(u)
            dst.append(u)
    return dst


def _mode_from_basename(base: str) -> str:
    """测速结果_<mode>_<ts>[.png/.json] → 模式显示名（未知返回空串；兼容含扩展名）"""
    if not base.startswith("测速结果_"):
        return ""
    rest = base[len("测速结果_"):]
    rest = os.path.splitext(rest)[0]  # 去掉 .png/.json（调用方可能带扩展名）
    rest = _MODE_TAIL_RE.sub("", rest)
    return _MODE_NAMES.get(rest, "")


def _last_run_line(last_result_path: str = "") -> str:
    """上次结果摘要行：优先本次会话结果，否则 output/ 最新 PNG"""
    target = last_result_path if last_result_path and os.path.exists(last_result_path) else ""
    if not target and os.path.exists(OUTPUT_DIR):
        pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
        if pngs:
            latest = max(pngs, key=lambda f: _safe_mtime(os.path.join(OUTPUT_DIR, f)))
            target = os.path.join(OUTPUT_DIR, latest)
    if not target:
        return "上次结果: 无"
    base = os.path.basename(target)
    mode = _mode_from_basename(base)  # v4.29.0：兼容毫秒后缀时间戳
    try:
        mt = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(target)))
    except OSError:
        mt = "?"
    return f"上次结果: {mt} {mode}".strip()


def _list_reports(limit: int = 15) -> list:
    """output/ 报告列表：PNG/JSON 按同名前缀配对，最新在前，最多 limit 组

    返回 [(basename, [文件...]), ...]，basename 不含扩展名
    """
    if not os.path.exists(OUTPUT_DIR):
        return []
    files = [f for f in os.listdir(OUTPUT_DIR)
             if f.endswith(".png") or f.endswith(".json")]
    groups: dict = {}
    for f in files:
        base = f[: f.rfind(".")]
        groups.setdefault(base, []).append(f)
    items = sorted(
        groups.items(),
        key=lambda kv: _safe_mtime(os.path.join(OUTPUT_DIR, kv[1][0])),
        reverse=True)
    return items[:limit]


def _append_subscribe_url(url: str) -> str:
    """把订阅 URL 追加到 代理.txt（去重/保持原换行风格与尾随换行状态），返回状态文本

    newline="" 读写：不做 \n→\r\n 翻译、不做通用换行归一，字节级保持原文件风格。
    v4.44.0：读写改走 _read_text_auto（utf-8-sig → gbk 自动探测），写回沿用原编码
    ——旧实现只按 utf-8-sig 读，中文 Windows 记事本默认 GBK 保存的 代理.txt
    会直接失败（返回"失败: ..."），且追加会把 GBK 文件改写成 UTF-8。
    """
    try:
        if not os.path.exists(SUBSCRIBE_FILE):
            with open(SUBSCRIBE_FILE, "w", encoding="utf-8", newline="") as f:
                f.write(url + "\n")
            return "已添加"
        raw, enc = _read_text_auto(SUBSCRIBE_FILE)
        if url in [l.strip() for l in raw.splitlines() if l.strip()]:
            return "该 URL 已在 代理.txt 中"
        nl = "\r\n" if "\r\n" in raw else "\n"
        ends = raw.endswith("\n") or raw.endswith("\r")
        # 追加模式用 utf-8（BOM 已在文件开头，避免中途再写一个 BOM）
        append_enc = "utf-8" if enc == "utf-8-sig" else enc
        with open(SUBSCRIBE_FILE, "a", encoding=append_enc, newline="") as f:
            if raw and not ends:
                f.write(nl)
            f.write(url + (nl if (ends or not raw) else ""))
        return "已添加"
    except Exception as e:
        return f"失败: {_safe_exc_str(e)}"


def _select_subscribe_urls(urls: list) -> list:
    """多条订阅时让用户手动选择（逗号分隔多选，如 1,3；回车=全部）；单条直接返回

    返回空列表表示用户取消（Ctrl+C），调用方应回菜单。
    """
    if len(urls) <= 1:
        return urls
    print(f"\n发现 {len(urls)} 条订阅：")
    for i, u in enumerate(urls, 1):
        print(f"  {i:>2}. {_mask_url(u)}")
    try:
        choice = input("选择要测的订阅（逗号分隔多选，如 1,3；回车=全部）: ").strip()
    except KeyboardInterrupt:
        return []
    if not choice:
        return urls
    idxs = []
    for part in choice.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
            if 1 <= v <= len(urls):
                idxs.append(v)
        except ValueError:
            pass
    if not idxs:
        print("[错误] 选择无效，使用全部订阅")
        return urls
    sel = [urls[i - 1] for i in dict.fromkeys(idxs)]  # 去重保序
    print(f"已选择 {len(sel)} 条订阅")
    logger.info("订阅选择: %s", ", ".join(_mask_url(u) for u in sel),
                extra=_ev("subscribe_select", {"urls": [_mask_url(u) for u in sel]}))
    return sel


def _current_settings_line() -> str:
    """设置摘要行（菜单 12 用）"""
    st = load_settings()
    return (f"当前设置: 测速窗口 {st['speed_window_seconds']}s | "
            f"并行 {st['workers']} | 自动打开报告 {'开' if st['auto_open_report'] else '关'}")


def show_menu(last_result_path: str = "", level: str = "main"):
    """显示交互菜单（v4.29.0 三级：main=一级 / more=二级 / maint=三级维护）"""
    # v4.38.0：去掉 shell=True（固定字符串无注入面，但规避子进程 shell 启动开销与风格问题）
    try:
        if sys.platform == "win32":
            os.system("cls")
        else:
            os.system("clear")
    except Exception:
        pass
    if level == "main":
        lines = ["1. 标准测试", "2. 下载速度", "3. AI 网站", "4. 所有流媒体",
                 "5. 快速检测", "6. 更多", "0. 退出"]
    elif level == "more":
        lines = ["1. 节点稳定性", "2. 结果对比", "3. 订阅分组对比",
                 "4. 节点筛选测速", "5. 查看上次结果", "6. 结果管理",
                 "7. 订阅管理", "8. 设置", "9. 维护", "0. 返回"]
    else:  # maint
        lines = ["1. 更新 mihomo 内核", "2. 环境信息",
                 "3. 清理旧报告", "0. 返回"]
    print("╔════════════════════════════════╗")
    # 菜单每行内容宽度（不含边框）固定为 32 个字符宽度
    title = "机场测速工具 v" + VERSION
    title_pad = 32 - _str_width(title)
    print(f"║{' ' * (title_pad // 2)}{title}{' ' * (title_pad - title_pad // 2)}║")
    print("╠════════════════════════════════╣")
    for line in lines:
        print(f"║ {_pad_right(line, 31)}║")
    print("╚════════════════════════════════╝")
    # 状态行（菜单重绘时刷新）
    urls = read_subscribe_urls()
    sub_txt = f"订阅文件: 已配置 ({len(urls)} 条)" if urls else "订阅文件: 未配置（测试时需手动输入 URL）"
    print(sub_txt)
    print(_last_run_line(last_result_path))
    if level == "main":
        print("提示: 回车=重绘菜单 · 连续两次 Ctrl+C=退出")
    else:
        print("提示: 回车=重绘菜单 · Ctrl+C=返回上级")


def _invalid_choice(choice: str) -> None:
    """菜单无效选择统一处理（空回车=重绘，直接返回）"""
    if not choice:
        return
    print("无效选择")
    logger.warning("无效菜单选择: %s", choice,
                   extra=_ev("invalid_input", {"choice": choice}))
    input("\n按 Enter 继续...")


def _menu_choose_sort() -> str:
    """排序方式选择（测速类入口共用），返回 sort_by；v4.33.0 默认改为订阅顺序"""
    print("\n排序方式：")
    print("  1. 订阅顺序（默认）")
    print("  2. 最大速度 降序")
    print("  3. 最大速度 升序")
    print("  4. 平均速度 降序")
    print("  5. 平均速度 升序")
    print("  6. 节点名 A→Z")
    print("  7. 节点名 Z→A")
    sort_choice = input("请选择 [1-7] (默认1): ").strip()
    sort_map = {"1": "none", "2": "max_desc", "3": "max_asc",
                "4": "avg_desc", "5": "avg_asc",
                "6": "name_asc", "7": "name_desc"}
    return sort_map.get(sort_choice, "none")


async def _menu_run_flow(mode: str, fast: bool = False, node_filter: str = "",
                         node_limit: int = 0, allow_manual: bool = True) -> str:
    """测速类入口共用：收集订阅 → 排序选择 → run_test → 自动打开报告 → 返回结果路径"""
    urls = read_subscribe_urls()
    if not urls:
        if not allow_manual:
            print("[错误] 未找到 代理.txt")
            input("\n按 Enter 返回菜单...")
            return ""
        manual = input("未找到 代理.txt，请输入订阅URL: ").strip()
        logger.debug(
            "手动输入订阅URL",
            extra=_ev("manual_subscribe_input",
                      {"url": _mask_url(manual) if manual else ""}))
        if manual:
            urls = [manual]
            try:
                save = input("保存该订阅 URL 到 代理.txt 吗？[y/N]: ").strip().lower()
            except KeyboardInterrupt:
                save = ""
            if save in ("y", "yes"):
                msg = _append_subscribe_url(manual)
                print(f"[信息] {msg}")
                if msg == "已添加":
                    logger.info("订阅 URL 已保存到 代理.txt",
                                extra=_ev("manual_subscribe_input",
                                          {"url": _mask_url(manual), "saved": True}))
                else:
                    logger.info("订阅 URL 未保存: %s", msg,
                                extra=_ev("manual_subscribe_input",
                                          {"url": _mask_url(manual), "saved": False}))
        else:
            return ""
    else:
        urls = _select_subscribe_urls(urls)  # 多条订阅手动选择
        if not urls:
            return ""  # 用户取消 → 回菜单
    sort_by = _menu_choose_sort()
    st = load_settings()
    last_result_path = await run_test(urls, mode, sort_by, fast=fast,
                                      workers=st.get("workers", DEFAULT_WORKERS),
                                      node_filter=node_filter, node_limit=node_limit,
                                      window_seconds=0 if fast else st.get("speed_window_seconds", 0))
    if last_result_path and os.path.exists(last_result_path) and st.get("auto_open_report", True):
        _open_report(last_result_path)
    input("\n按 Enter 返回菜单...")
    return last_result_path


async def _menu_filtered_run() -> str:
    """节点筛选测速（旧菜单 9）：关键字（任一匹配）或前 N 个"""
    filt = input("筛选（节点名关键字，如 香港 JP；N=10 只测前10个；回车=全部）: ").strip()
    node_filter = ""
    node_limit = 0
    if filt.upper().startswith("N="):
        try:
            node_limit = max(1, int(filt[2:]))
        except ValueError:
            print("[错误] 数量格式无效（示例: N=10）")
            input("\n按 Enter 返回菜单...")
            return ""
    else:
        node_filter = filt
    print("模式: 1.简单测速  2.标准测试  5.快速测速")
    mode_choice = input("请选择 [1/2/5] (默认1): ").strip()
    fast = mode_choice == "5"
    mode = "normal" if mode_choice == "2" else "speed"
    return await _menu_run_flow(mode, fast=fast, node_filter=node_filter,
                                node_limit=node_limit, allow_manual=False)


def _menu_view_last(last_result_path: str) -> None:
    """查看上次结果：优先本次会话结果，否则 output 最新 PNG"""
    target = last_result_path if last_result_path and os.path.exists(last_result_path) else ""
    if not target and os.path.exists(OUTPUT_DIR):
        pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
        if pngs:
            latest = max(pngs, key=lambda f: _safe_mtime(os.path.join(OUTPUT_DIR, f)))
            target = os.path.join(OUTPUT_DIR, latest)
    if target:
        _open_report(target)
    else:
        print("暂无结果文件")
    input("\n按 Enter 返回菜单...")


def _menu_manage_results() -> None:
    """结果管理（旧菜单 10）：最近报告，编号打开 / D+编号删除"""
    reports = _list_reports()
    if not reports:
        print("output 目录暂无报告")
    else:
        print("最近报告（输入编号=打开，D+编号=删除，回车=返回）：")
        for i, (base, files) in enumerate(reports, 1):
            fp = os.path.join(OUTPUT_DIR, base + ".png")
            if not os.path.exists(fp):
                fp = os.path.join(OUTPUT_DIR, files[0])
            try:
                mt = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
            except OSError:
                mt = "?"
            mode = _mode_from_basename(base)  # v4.29.0：兼容毫秒后缀时间戳
            print(f"  {i:>2}. {mt} {_pad_right(mode, 10)} {base}")
        act = input("操作: ").strip().upper()
        if act:
            try:
                if act.startswith("D"):
                    idx = int(act[1:])
                    if not (1 <= idx <= len(reports)):
                        raise IndexError  # v4.35.0：0/越界会命中负索引 reports[-1] 误删最旧报告
                    base, files = reports[idx - 1]
                    failed = []
                    for f in files:
                        try:
                            os.remove(os.path.join(OUTPUT_DIR, f))
                        except OSError as e:
                            # v4.44.0：不再吞异常后照报"已删除"（文件被占用/只读时误导用户）
                            failed.append((f, _safe_exc_str(e)))
                    if failed:
                        print(f"[警告] 已删除 {len(files) - len(failed)}/{len(files)} 个文件，"
                              f"以下删除失败：")
                        for f, why in failed:
                            print(f"  - {f}: {why}")
                        logger.warning("删除报告文件失败: %s",
                                       "; ".join(f for f, _ in failed))
                    else:
                        print(f"[OK] 已删除: {base}（{len(files)} 个文件）")
                else:
                    idx = int(act)
                    if not (1 <= idx <= len(reports)):
                        raise IndexError  # v4.35.0：0 会命中负索引误开最旧报告
                    base, files = reports[idx - 1]
                    pngs = [f for f in files if f.endswith(".png")]
                    _open_report(os.path.join(OUTPUT_DIR, pngs[0] if pngs else files[0]))
            except (ValueError, IndexError):
                print("[错误] 无效编号")
    input("\n按 Enter 返回菜单...")


def _menu_manage_subs() -> None:
    """订阅管理（旧菜单 11）：遮蔽显示 / 添加 / 删除 / 打开文件编辑"""
    while True:
        urls = read_subscribe_urls()
        print("\n当前订阅 URL（已遮蔽显示）：")
        if not urls:
            print("  （空）")
        for i, u in enumerate(urls, 1):
            print(f"  {i:>2}. {_mask_url(u)}")
        print("操作: A=添加  D+编号=删除  O=打开文件编辑  回车=返回")
        act = input(": ").strip().upper()
        if not act:
            break
        if act == "A":
            new_u = input("输入订阅 URL: ").strip()
            if not new_u:
                continue
            msg = _append_subscribe_url(new_u)
            print(f"[信息] {msg}")
            if msg == "已添加":
                logger.info("订阅 URL 已添加",
                            extra=_ev("manual_subscribe_input",
                                      {"url": _mask_url(new_u), "added": True}))
        elif act == "O":
            if os.path.exists(SUBSCRIBE_FILE):
                _open_report(SUBSCRIBE_FILE)
            else:
                print("[错误] 代理.txt 不存在")
        elif act.startswith("D"):
            try:
                idx = int(act[1:]) - 1
            except ValueError:
                print("[错误] 无效编号")
                continue
            if not (0 <= idx < len(urls)):
                print("[错误] 编号超出范围")
                continue
            target = urls[idx]
            try:
                # v4.44.0：按「utf-8-sig → gbk」自动探测读、按原编码写回。旧实现只按
                # utf-8-sig 读，GBK 文件抛的 UnicodeDecodeError 是 ValueError 子类，
                # 被 except ValueError 吞掉后误报"无效编号"（真实原因被掩盖）
                # 菜单显示行（非空非注释）→ 原始行号映射；逐行原样保留（newline=""）
                raw_text, enc = _read_text_auto(SUBSCRIBE_FILE)
                raw_lines = raw_text.splitlines(keepends=True)
                clean_idx = [i for i, l in enumerate(raw_lines)
                             if l.strip() and not l.strip().startswith("#")]
                del_raw = clean_idx[idx]
                rest_lines = [l for i, l in enumerate(raw_lines) if i != del_raw]
                with open(SUBSCRIBE_FILE, "w", encoding=enc, newline="") as f:
                    f.write("".join(rest_lines))
            except IndexError:
                print("[错误] 无效编号")
                continue
            except (OSError, UnicodeDecodeError, UnicodeEncodeError) as e:
                print(f"[错误] 删除失败: {_safe_exc_str(e)}")
                logger.warning("删除订阅 URL 失败: %s", _safe_exc_str(e))
                continue
            print(f"[OK] 已删除第 {idx + 1} 条")
            logger.info("订阅 URL 已删除",
                        extra=_ev("manual_subscribe_input",
                                  {"url": _mask_url(target), "deleted": True}))
        else:
            print("[错误] 无效操作")


def _menu_settings() -> None:
    """设置（旧菜单 12 + v4.29.0 稳定性窗口/大流量确认）"""
    print(_current_settings_line())
    print("操作: 1=测速窗口秒数  2=并行数  3=自动打开报告  4=恢复默认  "
          "5=稳定性窗口  6=大流量确认  7=保留报告份数  8=日志保留天数  回车=返回")
    act = input(": ").strip()
    try:
        if act == "1":
            try:
                v = int(input(f"测速窗口秒数 (3-30，当前 {load_settings()['speed_window_seconds']}): ").strip())
            except ValueError:
                print("[错误] 请输入数字")
            else:
                st = load_settings()
                st["speed_window_seconds"] = max(3, min(v, 30))
                save_settings(st)
                print(f"[OK] 测速窗口: {st['speed_window_seconds']}s（菜单模式生效；--fast 仍为 5s）")
        elif act == "2":
            try:
                v = int(input(f"并行数 (1-8，当前 {load_settings()['workers']}): ").strip())
            except ValueError:
                print("[错误] 请输入数字")
            else:
                st = load_settings()
                st["workers"] = max(1, min(v, 8))
                save_settings(st)
                print(f"[OK] 并行数: {st['workers']}")
        elif act == "3":
            v = input(f"自动打开报告 [y/N]（当前 {'开' if load_settings()['auto_open_report'] else '关'}）: ").strip().lower()
            st = load_settings()
            st["auto_open_report"] = v in ("y", "yes")
            save_settings(st)
            print(f"[OK] 自动打开报告: {'开' if st['auto_open_report'] else '关'}")
        elif act == "4":
            reset_settings()
            print(f"[OK] 已恢复默认: {_current_settings_line()}")
        elif act == "5":
            v = input(f"稳定性窗口 近N次 (5/10/20，当前 {load_settings()['stability_window']}): ").strip()
            if v not in ("5", "10", "20"):
                print("[错误] 只支持 5/10/20")
            else:
                st = load_settings()
                st["stability_window"] = int(v)
                save_settings(st)
                print(f"[OK] 稳定性窗口: 近 {st['stability_window']} 次")
        elif act == "6":
            v = input(f"大流量确认(>50节点) [y/N]（当前 {'开' if load_settings()['confirm_large_run'] else '关'}）: ").strip().lower()
            st = load_settings()
            st["confirm_large_run"] = v in ("y", "yes")
            save_settings(st)
            print(f"[OK] 大流量确认: {'开' if st['confirm_large_run'] else '关'}")
        elif act == "7":
            v = input(f"保留报告份数 (10/30/100，当前 {load_settings()['keep_reports']}): ").strip()
            if v not in ("10", "30", "100"):
                print("[错误] 只支持 10/30/100")
            else:
                st = load_settings()
                st["keep_reports"] = int(v)
                save_settings(st)
                print(f"[OK] 保留报告份数: {st['keep_reports']}")
        elif act == "8":
            v = input(f"日志保留天数 (7-365，当前 {load_settings()['keep_logs_days']}): ").strip()
            try:
                days = int(v)
                if not 7 <= days <= 365:
                    raise ValueError
                st = load_settings()
                st["keep_logs_days"] = days
                save_settings(st)
                print(f"[OK] 日志保留天数: {st['keep_logs_days']}")
            except ValueError:
                print("[错误] 请输入 7-365 的整数")
    except OSError as e:
        # 设置文件写失败（只读/权限/磁盘）不拖垮菜单
        print(f"[错误] 保存设置失败: {_safe_exc_str(e)}")
        logger.warning("保存设置失败: %s", _safe_exc_str(e))
    input("\n按 Enter 返回菜单...")


def _menu_env_info() -> None:
    """环境信息（旧菜单 13）：版本/依赖/mihomo/订阅/文件统计（标签列统一 16 显示宽对齐）"""
    print("=" * 50)
    print(f"{_pad_right('工具版本', 16)}: v{VERSION}")
    print(f"{_pad_right('Python', 16)}: {sys.version.split()[0]} ({sys.platform})")
    print(f"{_pad_right('依赖', 16)}: aiohttp {_pkg_version('aiohttp')} / PyYAML {_pkg_version('PyYAML')} / "
          f"Pillow {_pkg_version('Pillow')} / tqdm {_pkg_version('tqdm')} / "
          f"requests {_pkg_version('requests')}")
    print(f"{_pad_right('cloudscraper', 16)}: {'可用' if HAS_CLOUDSCRAPER else '未安装'} | "
          f"yt-dlp: {'可用' if HAS_YTDLP else '未安装'}")
    cur_bin = ""
    if os.path.exists(MIHOMO_DIR):
        for f in os.listdir(MIHOMO_DIR):
            if f.startswith("mihomo") and (f.endswith(".exe") or "." not in f):
                cur_bin = os.path.join(MIHOMO_DIR, f)
                break
    ver = MihomoEngine._get_mihomo_version(cur_bin) if cur_bin else ""
    print(f"{_pad_right('mihomo', 16)}: {ver or '未安装'}（{cur_bin or '无'}）")
    urls = read_subscribe_urls()
    print(f"{_pad_right('订阅', 16)}: {len(urls)} 条" + ("（未配置）" if not urls else ""))
    for d, name in ((OUTPUT_DIR, "报告文件"), (LOG_DIR, "日志文件")):
        try:
            n = len(os.listdir(d)) if os.path.isdir(d) else 0
            print(f"{_pad_right(name, 16)}: {n}")
        except OSError:
            pass
    print(f"{_pad_right('当前设置', 16)}: 测速窗口 {load_settings()['speed_window_seconds']}s | "
          f"并行 {load_settings()['workers']} | "
          f"自动打开报告 {'开' if load_settings()['auto_open_report'] else '关'}")
    print("=" * 50)
    input("\n按 Enter 返回菜单...")


def _menu_update_kernel() -> None:
    """更新 mihomo 内核（旧菜单 6）：版本对比 + 下载 + 原子替换"""
    cur_bin = ""
    if os.path.exists(MIHOMO_DIR):
        for f in os.listdir(MIHOMO_DIR):
            if f.startswith("mihomo") and (f.endswith(".exe") or "." not in f):
                cur_bin = os.path.join(MIHOMO_DIR, f)
                break
    cur_ver = MihomoEngine._get_mihomo_version(cur_bin) if cur_bin else ""
    target_ver = MihomoEngine._get_latest_tag()
    if cur_ver:
        print(f"当前版本: {cur_ver}" + (f" → 目标版本: {target_ver}" if target_ver else ""))
    elif target_ver:
        print(f"目标版本: {target_ver}")
    print("正在更新 mihomo 内核...")
    tmp_dir = ""  # v4.44.0：提到 try 外——旧实现在异常路径（下载/解压抛错）漏删临时目录（约 47MB）
    try:
        tmp_dir = tempfile.mkdtemp(prefix="mihomo_update_")
        binary = MihomoEngine._download_mihomo(target_dir=tmp_dir)
        if binary:
            # 原子替换：旧目录 rename 为 .bak → move 新内核 → 成功删备份 / 失败回滚
            bak = MIHOMO_DIR + ".bak"
            if os.path.exists(MIHOMO_DIR):
                if os.path.exists(bak):
                    shutil.rmtree(bak, ignore_errors=True)
                os.rename(MIHOMO_DIR, bak)  # 同盘 rename 原子；失败时旧内核原样保留
            os.makedirs(MIHOMO_DIR, exist_ok=True)
            dst = os.path.join(MIHOMO_DIR, os.path.basename(binary))
            try:
                shutil.move(binary, dst)
            except Exception:
                # move 失败：回滚旧内核
                if os.path.exists(bak):
                    if os.path.exists(MIHOMO_DIR):
                        shutil.rmtree(MIHOMO_DIR, ignore_errors=True)
                    os.rename(bak, MIHOMO_DIR)
                raise
            if os.path.exists(bak):
                shutil.rmtree(bak, ignore_errors=True)  # 成功后清理备份
            new_ver = MihomoEngine._get_mihomo_version(dst)
            logger.info("mihomo 更新完成: %s", dst,
                        extra=_ev("mihomo_update", {"ok": True, "path": dst,
                                                    "version": new_ver}))
            print(f"[OK] 更新完成: {dst}" + (f" ({new_ver})" if new_ver else ""))
        else:
            logger.error("mihomo 更新失败（下载或解压失败）",
                         extra=_ev("mihomo_update", {"ok": False, "error": "download/unzip"}))
            print("[错误] 更新失败")
    except Exception as e:
        logger.error("mihomo 更新失败: %s", _safe_exc_str(e),
                     extra=_ev("mihomo_update", {"ok": False, "error": _safe_exc_str(e)[:200]}))
        print(f"[错误] 更新失败: {_safe_exc_str(e)}")
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)  # v4.44.0：成功/失败都清理临时目录
    input("\n按 Enter 返回菜单...")


def _menu_stability() -> None:
    """节点稳定性（二级 1，数据=profiles.json）：默认平均速度降序，r=按可达率降序"""
    try:
        data = load_profiles()
    except Exception as e:
        print(f"[错误] 档案读取失败: {_safe_exc_str(e)}")
        input("\n按 Enter 返回菜单...")
        return
    window = load_settings().get("stability_window", 10)
    if len(data.get("runs", [])) < 2:
        print("历史数据不足（至少需要 2 次测试），先跑几次测试再来看稳定性")
        input("\n按 Enter 返回菜单...")
        return
    rows = node_stability_report(data, window)
    if not rows:
        print("档案为空")
        input("\n按 Enter 返回菜单...")
        return
    by_reach = False
    while True:
        print(f"\n节点稳定性（近 {window} 次）  [r]=按可达率排序  回车=返回")
        print(f"{'分层':<6} {'节点':<26} {'出现':>7} {'可达':>6} {'平均速度':>12} {'波动'}")
        print("-" * 70)
        for row in rows:
            name = _trunc_width(_flag_to_text(row["name"]), 26)
            if row["layer"] == "新面孔":
                appear_txt = "首见"
                reach_txt = "-"
            else:
                appear_txt = f"{row['appear']}/{row['appear_total']}"
                reach_txt = f"{row['reach'] * 100:.0f}%" if row["reach"] is not None else "-"
            avg_txt = f"{row['avg']:.1f}MB/s" if row["avg"] is not None else "--"
            sigma_txt = f"±{row['sigma']:.1f}" if row["sigma"] is not None else "-"
            print(f"[{_pad_right(row['layer'], 4)}] {_pad_right(name, 26)} "
                  f"{appear_txt:>7} {reach_txt:>6} {avg_txt:>12} {sigma_txt}")
        try:
            act = input(": ").strip().lower()
        except KeyboardInterrupt:
            return
        if act == "r":
            by_reach = not by_reach
            if by_reach:
                rows.sort(key=lambda x: (x["reach"] is None, -(x["reach"] or 0)))
            else:
                rows.sort(key=lambda x: (x["avg"] is None, -(x["avg"] or 0)))
            continue
        return


def _menu_compare() -> None:
    """结果对比（二级 2，v4.30.0）：选两次 run 横比速度/延迟/解锁/排名差分"""
    try:
        data = load_profiles()
    except Exception as e:
        print(f"[错误] 档案读取失败: {_safe_exc_str(e)}")
        input("\n按 Enter 返回菜单...")
        return
    runs = data.get("runs") or []
    if len(runs) < 2:
        print("历史数据不足（至少需要 2 次测试）")
        input("\n按 Enter 返回菜单...")
        return
    metas = list(reversed(runs[-15:]))  # 最新在前，最多 15 条
    print("\n最近测试（[晚高峰]=18-23点或周末）：")
    for i, r in enumerate(metas, 1):
        tag = " [晚高峰]" if _is_peak_hour(r["ts"]) else ""
        print(f"  {i:>2}. {r['ts']}  {_pad_right(_MODE_NAMES.get(r['mode'], r['mode']), 8)} "
              f"{r['node_count']} 节点{tag}")
    try:
        inp = input("输入两个编号（如 1 3，前者为基准）: ").strip()
    except KeyboardInterrupt:
        return
    parts = [p for p in inp.replace("，", ",").replace(" ", ",").split(",") if p]
    try:
        ia, ib = int(parts[0]) - 1, int(parts[1]) - 1
    except (ValueError, IndexError):
        print("[错误] 编号无效")
        input("\n按 Enter 返回菜单...")
        return
    if not (0 <= ia < len(metas) and 0 <= ib < len(metas)):
        # v4.44.0：0/越界会命中负索引 metas[-1]（对比的其实是最后一条，用户不知情）
        print("[错误] 编号无效")
        input("\n按 Enter 返回菜单...")
        return
    ra, rb = metas[ia], metas[ib]
    res = run_compare_report(data, ra["run_id"], rb["run_id"])
    if res.get("error"):
        print(f"[错误] {res['error']}")
        input("\n按 Enter 返回菜单...")
        return
    print(f"\n对比: {ra['ts']} ({ra['mode']})  →  {rb['ts']} ({rb['mode']})")
    if res.get("note"):
        print(f"[提示] {res['note']}")
    print(f"{_pad_right('节点', 26)} {'基准速度':>9} {'对比速度':>9} {'变化':>7} "
          f"{'基准延迟':>9} {'对比延迟':>9} {'排名':>6}")
    print("-" * 82)
    for row in res["rows"]:
        name = _trunc_width(_flag_to_text(row["name"]), 26)
        sa = f"{row['speed_a']:.1f}MB/s" if row["speed_a"] is not None else "--"
        sb = f"{row['speed_b']:.1f}MB/s" if row["speed_b"] is not None else "--"
        la = f"{row['lat_a']:.0f}ms" if row["lat_a"] is not None else "--"
        lb = f"{row['lat_b']:.0f}ms" if row["lat_b"] is not None else "--"
        rk = f"{row['rank_a'] or '-'}→{row['rank_b'] or '-'}"
        print(f"{_pad_right(name, 26)} {sa:>9} {sb:>9} {row['delta_txt']:>7} "
              f"{la:>9} {lb:>9} {rk:>6}")
    if res.get("only_a") or res.get("only_b"):
        print(f"（基准独有 {res['only_a']} 个 / 对比独有 {res['only_b']} 个节点未列出）")
    input("\n按 Enter 返回菜单...")


def _menu_group_report() -> None:
    """订阅分组对比（二级 3，v4.31.0）：按订阅来源横评（数据=结果 JSON 的 sub_index）"""
    try:
        data = load_profiles()
    except Exception as e:
        print(f"[错误] 档案读取失败: {_safe_exc_str(e)}")
        input("\n按 Enter 返回菜单...")
        return
    runs = data.get("runs") or []
    if not runs:
        print("档案中没有测试记录")
        input("\n按 Enter 返回菜单...")
        return
    metas = list(reversed(runs[-15:]))  # 最新在前
    print("\n最近测试（回车=用最新一次，输入编号选历史）：")
    for i, r in enumerate(metas, 1):
        print(f"  {i:>2}. {r['ts']}  {_pad_right(_MODE_NAMES.get(r['mode'], r['mode']), 8)} "
              f"{r['node_count']} 节点")
    try:
        inp = input("选择: ").strip()
    except KeyboardInterrupt:
        return
    run_id = ""
    if inp:
        try:
            idx = int(inp) - 1
        except ValueError:
            print("[错误] 编号无效")
            input("\n按 Enter 返回菜单...")
            return
        if not (0 <= idx < len(metas)):
            # v4.44.0：0/越界会命中负索引 metas[-1]（把最后一次 run 当选择结果用）
            print("[错误] 编号无效")
            input("\n按 Enter 返回菜单...")
            return
        run_id = metas[idx]["run_id"]
    res = subscription_group_report(data, run_id)
    if res.get("error"):
        print(f"[错误] {res['error']}")
        input("\n按 Enter 返回菜单...")
        return
    run = res["run"]
    print(f"\n订阅分组对比: {run['ts']} ({run['mode']})")
    if res.get("note"):
        print(f"[提示] {res['note']}")
    print(f"{_pad_right('分组', 8)} {'节点数':>6} {'平均速度':>10} {'最高速度':>10} "
          f"{'解锁率':>8} {'平均延迟':>9} {'风险均值':>8}")
    print("-" * 68)
    for row in res["rows"]:
        avg = f"{row['avg_speed']:.1f}MB/s" if row["avg_speed"] is not None else "--"
        mx = f"{row['max_speed']:.1f}MB/s" if row["max_speed"] else "--"
        rate = f"{row['unlock_rate'] * 100:.0f}%" if row["unlock_rate"] is not None else "--"
        lat = f"{row['avg_lat']:.0f}ms" if row["avg_lat"] is not None else "--"
        risk = f"{row['avg_risk']:.0f}" if row["avg_risk"] is not None else "--"
        print(f"{_pad_right(str(row['group']), 8)} {row['n']:>6} {avg:>10} {mx:>10} "
              f"{rate:>8} {lat:>9} {risk:>8}")
    input("\n按 Enter 返回菜单...")


def _menu_cleanup() -> None:
    """清理旧报告与日志（维护 3，v4.31.0）：先统计后确认执行"""
    st = load_settings()
    keep_r = st.get("keep_reports", KEEP_REPORTS_DEFAULT)
    keep_d = st.get("keep_logs_days", KEEP_LOGS_DAYS_DEFAULT)
    try:
        stat = cleanup_outputs(keep_r, keep_d, dry_run=True)
    except Exception as e:
        print(f"[错误] 统计失败: {_safe_exc_str(e)}")
        input("\n按 Enter 返回菜单...")
        return
    total = _fmt_size(stat["freed_bytes"])
    print(f"\n产物清理（保留最近 {keep_r} 份报告 / 最近 {keep_d} 天日志；可在设置页调整）：")
    print(f"  将删除: 报告 {stat['reports_deleted']} 份、日志 {stat['logs_deleted']} 个，"
          f"释放约 {total}")
    if not stat["reports_deleted"] and not stat["logs_deleted"]:
        print("  当前无需清理")
        input("\n按 Enter 返回菜单...")
        return
    try:
        act = input("确认执行清理？[y/N]: ").strip().lower()
    except KeyboardInterrupt:
        return
    if act in ("y", "yes"):
        try:
            done = cleanup_outputs(keep_r, keep_d)
        except Exception as e:
            print(f"[错误] 清理失败: {_safe_exc_str(e)}")
            input("\n按 Enter 返回菜单...")
            return
        logger.info("手动产物清理: 报告 -%d 份、日志 -%d 个",
                    done["reports_deleted"], done["logs_deleted"],
                    extra=_ev("profiles_cleanup", done))
        print(f"[OK] 已清理: 报告 {done['reports_deleted']} 份、日志 {done['logs_deleted']} 个，"
              f"释放 {_fmt_size(done['freed_bytes'])}")
    input("\n按 Enter 返回菜单...")


async def async_main():
    """异步主入口"""
    # 检查参数
    args = sys.argv[1:]

    # 直接传参模式
    show_menu_mode = False
    if args:
        url = []  # v4.44.0：统一 list 语义（追加 + 去重），不再让 -i 与位置 URL 相互覆盖
        url_source_given = False  # 显式给了订阅来源却一条都没解析出来时，明确提示而非静默进菜单
        mode = "basic"
        fast = False
        workers = DEFAULT_WORKERS
        skip_next = None
        for i, arg in enumerate(args):
            if skip_next is not None and i <= skip_next:
                continue
            if arg == "--full":
                mode = "full"
            elif arg == "--fast":
                fast = True
            elif arg == "--quick":
                mode = "quick"  # v4.30.0：并行近似测速 + 4 核心流媒体
            elif arg.startswith("--workers="):
                try:
                    v = int(arg.split("=", 1)[1])
                    if not (1 <= v <= MAX_WORKERS):
                        logger.warning("--workers=%d 超出范围 1-%d，已钳制", v, MAX_WORKERS)
                    workers = max(1, min(v, MAX_WORKERS))
                except ValueError:
                    logger.warning("--workers 参数无效: %s，使用默认值 %d", arg, DEFAULT_WORKERS)
            elif arg == "--workers":
                if i + 1 >= len(args):
                    logger.warning("--workers 缺少参数，使用默认值 %d", DEFAULT_WORKERS)
                else:
                    try:
                        v = int(args[i + 1])
                        if not (1 <= v <= MAX_WORKERS):
                            logger.warning("--workers=%d 超出范围 1-%d，已钳制", v, MAX_WORKERS)
                        workers = max(1, min(v, MAX_WORKERS))
                        skip_next = i + 1
                    except ValueError:
                        # v4.27.0：后跟非数字（如 --workers --full）时不吞掉该 flag
                        logger.warning("--workers 参数无效: %s，使用默认值", args[i + 1])
            elif arg == "--help" or arg == "-h":
                print("用法:")
                print("  python core/speed_test.py                    交互菜单")
                print("  python core/speed_test.py <订阅URL>          轻量测速")
                print("  python core/speed_test.py <URL> --full       完整测速")
                print("  python core/speed_test.py <URL> --fast       快速模式(5s窗口/跳过IP检测)")
                print("  python core/speed_test.py <URL> --quick      快速检测(并行近似测速+4核心流媒体)")
                print("  python core/speed_test.py <URL> --workers N  流媒体/IP/网页并行数(1-8,默认4;测速恒串行)")
                print("  python core/speed_test.py <URL> --workers=4  同上（等号形式）")
                print("  python core/speed_test.py -i file.txt        从文件读URL")
                print("  python core/speed_test.py --menu             显示菜单")
                print("  python core/speed_test.py --report           打开上次报告")
                return
            elif arg == "--report":
                # 查找最新的 PNG 报告并打开
                if os.path.exists(OUTPUT_DIR):
                    pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
                    if pngs:
                        latest = max(pngs, key=lambda f: _safe_mtime(os.path.join(OUTPUT_DIR, f)))
                        latest_path = os.path.join(OUTPUT_DIR, latest)
                        logger.info("打开最新报告: %s", latest_path)
                        _open_report(latest_path)
                    else:
                        logger.error("output 目录中没有 PNG 报告")
                else:
                    logger.error("output 目录不存在")
                return
            elif arg == "--menu":
                show_menu_mode = True
                break
            elif arg.startswith("http://") or arg.startswith("https://"):
                # v4.39.0：多个位置 URL 合并解析（旧实现后一个静默覆盖前一个）
                # v4.44.0：与 -i 文件内容也合并（旧实现 `url = url_list` 直接覆盖）
                if url or url_source_given:
                    logger.warning("检测到多个订阅来源，合并解析")
                url_source_given = True
                _merge_urls(url, [arg])
            elif arg == "-i":
                if i + 1 >= len(args):
                    logger.warning("-i 缺少文件参数")
                    continue
                skip_next = i + 1
                filepath = args[i + 1]
                url_source_given = True
                if os.path.exists(filepath):
                    found = []
                    # v4.36.0：先读字节再依次尝试 utf-8-sig → gbk——旧实现 try 只包 open()
                    # 不包迭代，UnicodeDecodeError 在 for line 时抛出，回退分支是死代码，
                    # GBK 文件会在迭代时未捕获崩溃
                    try:
                        raw = open(filepath, "rb").read()
                    except OSError as e:
                        logger.error("读取文件失败: %s", _safe_exc_str(e))
                        raw = b""
                    text = None
                    for enc in ("utf-8-sig", "gbk"):
                        try:
                            text = raw.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if text is None:
                        text = raw.decode("utf-8", errors="replace")
                    for line in text.splitlines():
                        l = line.strip()
                        if l and not l.startswith("#"):
                            found.append(l)
                    if found:
                        if url:
                            logger.warning("检测到多个订阅来源，合并解析")
                        _merge_urls(url, found)  # v4.44.0：追加而非覆盖
                    else:
                        # v4.44.0：文件为空/全是注释 → 明确提示（旧实现让 url 变成 []，
                        # 静默掉进交互菜单，用户以为正在测速）
                        logger.warning("-i 文件未解析到可用 URL: %s", filepath)
                        print(f"[警告] 文件未解析到可用订阅 URL: {filepath}")
                else:
                    logger.error("文件不存在: %s", filepath)
            else:
                logger.warning("未知参数: %s（-h 查看帮助）", arg)
        if url and not show_menu_mode:
            result = await run_test(url, mode, fast=fast, workers=workers)
            if result and os.path.exists(result):
                _open_report(result)
            return
        if url_source_given and not show_menu_mode:
            # v4.44.0：显式给了订阅来源却一条可用 URL 都没解析到 → 明确说明，不静默进菜单
            # （show_menu 会清屏，先停一下让用户看清原因）
            print("[错误] 未解析到可用的订阅 URL，已回到交互菜单")
            logger.warning("未解析到可用的订阅 URL（位置参数/-i 文件为空或无有效行）")
            try:
                input("按 Enter 进入菜单...")
            except (EOFError, KeyboardInterrupt):
                pass

    # 交互菜单模式（v4.29.0 三级：main/more/maint；Ctrl+C 一次返回上级，一级两次退出）
    last_result_path = ""
    menu_level = "main"
    ctrl_c_count = 0
    prompt_map = {"main": "[0-6]", "more": "[0-9]", "maint": "[0-3]"}
    while True:
        show_menu(last_result_path, menu_level)
        try:
            choice = input(f"\n请选择 {prompt_map[menu_level]}: ").strip()
            ctrl_c_count = 0  # 正常输入后清零
        except KeyboardInterrupt:
            if menu_level != "main":
                print("\n（返回上级菜单）")
                menu_level = "main" if menu_level == "more" else "more"
                ctrl_c_count = 0
                continue
            ctrl_c_count += 1
            if ctrl_c_count >= 2:
                print("\n再见!")
                break
            print("\n（再按一次 Ctrl+C 退出，或直接回车返回菜单）")
            try:
                input()
            except KeyboardInterrupt:
                print("\n再见!")
                break
            continue
        logger.debug("菜单选择: %s（级别=%s）", choice, menu_level,
                     extra=_ev("menu_choice", {"choice": choice, "level": menu_level}))

        try:
            if menu_level == "main":
                if choice in ("1", "2", "3", "4"):
                    mode_map = {"1": "normal", "2": "speed",
                                "3": "streaming_ai", "4": "streaming_all"}
                    last_result_path = await _menu_run_flow(mode_map[choice])
                elif choice == "5":
                    last_result_path = await _menu_run_flow("quick")  # v4.30.0：快速检测
                elif choice == "6":
                    menu_level = "more"
                    continue
                elif choice == "0":
                    print("再见!")
                    break
                else:
                    _invalid_choice(choice)
            elif menu_level == "more":
                if choice == "1":
                    _menu_stability()
                elif choice == "2":
                    _menu_compare()  # v4.30.0：结果对比
                elif choice == "3":
                    _menu_group_report()  # v4.31.0：订阅分组对比
                elif choice == "4":
                    last_result_path = await _menu_filtered_run()
                elif choice == "5":
                    _menu_view_last(last_result_path)
                elif choice == "6":
                    _menu_manage_results()
                elif choice == "7":
                    _menu_manage_subs()
                elif choice == "8":
                    _menu_settings()
                elif choice == "9":
                    menu_level = "maint"
                    continue
                elif choice == "0":
                    menu_level = "main"
                    continue
                else:
                    _invalid_choice(choice)
            else:  # maint
                if choice == "1":
                    _menu_update_kernel()
                elif choice == "2":
                    _menu_env_info()
                elif choice == "3":
                    _menu_cleanup()  # v4.31.0：清理旧报告与日志
                elif choice == "0":
                    menu_level = "more"
                    continue
                else:
                    _invalid_choice(choice)
        except KeyboardInterrupt:
            # v4.35.0：子菜单/功能内 Ctrl+C 不再直接退出程序——返回上级菜单重绘
            # （测试运行中的 Ctrl+C 由 run_test 内部捕获生成部分结果，不会到达这里）
            print("\n（返回上级菜单）")
            if menu_level != "main":
                menu_level = "main" if menu_level == "more" else "more"
            continue


def main():
    """同步入口"""
    atexit.register(_cleanup_procs)  # 兜底终止残留 mihomo 进程
    # 直接 python 运行时控制台可能是 GBK：切到 UTF-8 保证菜单边框/中文正常（run.bat 已 chcp）
    try:
        if sys.platform == "win32" and sys.stdout.isatty():
            os.system("chcp 65001 >nul")
    except Exception:
        pass
    # 重定向/管道输出用 UTF-8（Windows 默认 ANSI 代码页会出乱码）
    try:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8")
        if not sys.stderr.isatty():
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    setup_logging()
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("再见!")
    except asyncio.CancelledError:
        logger.info("再见!")
    except EOFError:
        pass  # 管道输入提前结束（如 echo 1 | python ...）：正常退出，不记异常
    except Exception:
        logger.exception("程序异常退出", extra=_ev("run_exception", {"phase": "main"}))
        sys.exit(1)  # v4.35.0：真实异常置非零退出码（run.bat `if errorlevel 1 pause` 兜底可见报错）
    finally:
        _cleanup_empty_log()

__all__ = ['_MODE_NAMES', '_last_run_line', '_list_reports', '_append_subscribe_url',
           '_select_subscribe_urls', '_current_settings_line', '_open_report',
           '_safe_mtime', '_read_text_auto', '_merge_urls',
           'show_menu', 'async_main', 'main']
