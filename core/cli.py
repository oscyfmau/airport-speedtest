#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行入口：参数解析 / 交互菜单 / 内核更新"""
import asyncio
import atexit
import os
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
        logger.error(f"打开报告失败: {path} ({e})")
        return False


_MODE_NAMES = {"speed": "简单测速", "basic": "简单测速", "normal": "标准测试",
               "full": "完整测速", "streaming": "流媒体", "streaming_ai": "AI流媒体",
               "streaming_all": "全部流媒体"}


def _last_run_line(last_result_path: str = "") -> str:
    """上次结果摘要行：优先本次会话结果，否则 output/ 最新 PNG"""
    target = last_result_path if last_result_path and os.path.exists(last_result_path) else ""
    if not target and os.path.exists(OUTPUT_DIR):
        pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
        if pngs:
            latest = max(pngs, key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)))
            target = os.path.join(OUTPUT_DIR, latest)
    if not target:
        return "上次结果: 无"
    base = os.path.basename(target)
    mode = ""
    if base.startswith("测速结果_"):
        mode = _MODE_NAMES.get(base[len("测速结果_"):].rsplit("_", 2)[0], "")
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
        key=lambda kv: os.path.getmtime(os.path.join(OUTPUT_DIR, kv[1][0])),
        reverse=True)
    return items[:limit]


def _append_subscribe_url(url: str) -> str:
    """把订阅 URL 追加到 代理.txt（去重/保持原换行风格与尾随换行状态），返回状态文本

    newline="" 读写：不做 \n→\r\n 翻译、不做通用换行归一，字节级保持原文件风格。
    """
    try:
        exists = os.path.exists(SUBSCRIBE_FILE)
        if exists:
            with open(SUBSCRIBE_FILE, "r", encoding="utf-8-sig", newline="") as fr:
                raw = fr.read()
            if url in [l.strip() for l in raw.splitlines() if l.strip()]:
                return "该 URL 已在 代理.txt 中"
            nl = "\r\n" if "\r\n" in raw else "\n"
            ends = raw.endswith("\n") or raw.endswith("\r")
            with open(SUBSCRIBE_FILE, "a", encoding="utf-8", newline="") as f:
                if raw and not ends:
                    f.write(nl)
                f.write(url + (nl if (ends or not raw) else ""))
            return "已添加"
        with open(SUBSCRIBE_FILE, "w", encoding="utf-8", newline="") as f:
            f.write(url + "\n")
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


def show_menu(last_result_path: str = ""):
    """显示交互菜单"""
    subprocess.call("cls" if sys.platform == "win32" else "clear", shell=True)
    print("╔════════════════════════════════╗")
    # 菜单每行内容宽度（不含边框）固定为 32 个字符宽度
    title = "机场测速工具 v" + VERSION
    title_pad = 32 - _str_width(title)
    print(f"║{' ' * (title_pad // 2)}{title}{' ' * (title_pad - title_pad // 2)}║")
    print("╠════════════════════════════════╣")
    print(f"║ {_pad_right('1. 简单测速', 31)}║")
    print(f"║ {_pad_right('2. 标准测试', 31)}║")
    print(f"║ {_pad_right('3. AI流媒体', 31)}║")
    print(f"║ {_pad_right('4. 全部流媒体', 31)}║")
    print(f"║ {_pad_right('5. 查看上次结果', 31)}║")
    print(f"║ {_pad_right('6. 更新 mihomo 内核', 31)}║")
    print(f"║ {_pad_right('7. 退出', 31)}║")
    print(f"║ {_pad_right('8. 快速测速(5s/跳过IP)', 31)}║")
    print("╠════════════════════════════════╣")
    print(f"║ {_pad_right('9. 节点筛选测速', 31)}║")
    print(f"║ {_pad_right('10. 结果管理', 31)}║")
    print(f"║ {_pad_right('11. 订阅管理', 31)}║")
    print(f"║ {_pad_right('12. 设置', 31)}║")
    print(f"║ {_pad_right('13. 环境信息', 31)}║")
    print("╚════════════════════════════════╝")
    # 状态行（菜单重绘时刷新）
    urls = read_subscribe_urls()
    sub_txt = f"订阅文件: 已配置 ({len(urls)} 条)" if urls else "订阅文件: 未配置（测试时需手动输入 URL）"
    print(sub_txt)
    print(_last_run_line(last_result_path))
    print("提示: 回车=重绘菜单 · 连续两次 Ctrl+C=退出")


async def async_main():
    """异步主入口"""
    # 检查参数
    args = sys.argv[1:]

    # 直接传参模式
    show_menu_mode = False
    if args:
        url = None
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
            elif arg.startswith("--workers="):
                try:
                    workers = max(1, min(int(arg.split("=", 1)[1]), MAX_WORKERS))
                except ValueError:
                    logger.warning("--workers 参数无效: %s，使用默认值 %d", arg, DEFAULT_WORKERS)
            elif arg == "--workers":
                if i + 1 >= len(args):
                    logger.warning("--workers 缺少参数，使用默认值 %d", DEFAULT_WORKERS)
                else:
                    try:
                        workers = max(1, min(int(args[i + 1]), MAX_WORKERS))
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
                        latest = max(pngs, key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)))
                        latest_path = os.path.join(OUTPUT_DIR, latest)
                        logger.info(f"打开最新报告: {latest_path}")
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
                url = arg
            elif arg == "-i":
                if i + 1 >= len(args):
                    logger.warning("-i 缺少文件参数")
                    continue
                skip_next = i + 1
                filepath = args[i + 1]
                if os.path.exists(filepath):
                    url_list = []
                    # utf-8-sig 兼容 BOM；GBK 失败时回退
                    try:
                        fh = open(filepath, "r", encoding="utf-8-sig")
                    except UnicodeDecodeError:
                        fh = open(filepath, "r", encoding="gbk", errors="replace")
                    with fh:
                        for line in fh:
                            l = line.strip()
                            if l and not l.startswith("#"):
                                url_list.append(l)
                    url = url_list  # 支持多 URL 合并解析
                else:
                    logger.error("文件不存在: %s", filepath)
            else:
                logger.warning("未知参数: %s（-h 查看帮助）", arg)
        if url and not show_menu_mode:
            result = await run_test(url, mode, fast=fast, workers=workers)
            if result and os.path.exists(result):
                _open_report(result)
            return

    # 交互菜单模式
    last_result_path = ""
    ctrl_c_count = 0
    while True:
        show_menu(last_result_path)
        try:
            choice = input("\n请选择 [1-13]: ").strip()
            ctrl_c_count = 0  # 正常输入后清零
        except KeyboardInterrupt:
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
        logger.debug("菜单选择: %s", choice, extra=_ev("menu_choice", {"choice": choice}))

        if choice in ("1", "2", "3", "4", "8"):
            fast = choice == "8"  # 快速测速：5s 窗口/跳过 IP 检测
            urls = read_subscribe_urls()
            if not urls:
                manual = input("未找到 代理.txt，请输入订阅URL: ").strip()
                logger.debug(
                    "手动输入订阅URL",
                    extra=_ev("manual_subscribe_input",
                              {"url": _mask_url(manual) if manual else ""}))
                if manual:
                    urls = [manual]
                    # 询问保存到 代理.txt（默认不保存；重复行跳过）
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
                    continue
            else:
                urls = _select_subscribe_urls(urls)  # 多条订阅手动选择
                if not urls:
                    continue  # 用户取消 → 回菜单
            mode_map = {"1": "speed", "2": "normal", "3": "streaming_ai",
                        "4": "streaming_all", "8": "speed"}
            mode = mode_map.get(choice, "speed")

            print("\n排序方式：")
            print("  1. 订阅顺序")
            print("  2. 最大速度 降序 ⬅ 默认")
            print("  3. 最大速度 升序")
            print("  4. 平均速度 降序")
            print("  5. 平均速度 升序")
            print("  6. 节点名 A→Z")
            print("  7. 节点名 Z→A")
            sort_choice = input("请选择 [1-7] (默认2): ").strip()
            sort_map = {"1": "none", "2": "max_desc", "3": "max_asc",
                        "4": "avg_desc", "5": "avg_asc",
                        "6": "name_asc", "7": "name_desc"}
            sort_by = sort_map.get(sort_choice, "max_desc")

            last_result_path = await run_test(urls, mode, sort_by, fast=fast,
                                              workers=load_settings().get("workers", DEFAULT_WORKERS),
                                              window_seconds=0 if fast else load_settings().get("speed_window_seconds", 0))
            if last_result_path and os.path.exists(last_result_path) and load_settings().get("auto_open_report", True):
                _open_report(last_result_path)
            input("\n按 Enter 返回菜单...")

        elif choice == "9":
            # 节点筛选测速：关键字（任一匹配）或前 N 个节点
            filt = input("筛选（节点名关键字，如 香港 JP；N=10 只测前10个；回车=全部）: ").strip()
            node_filter = ""
            node_limit = 0
            if filt.upper().startswith("N="):
                try:
                    node_limit = max(1, int(filt[2:]))
                except ValueError:
                    print("[错误] 数量格式无效（示例: N=10）")
                    input("\n按 Enter 返回菜单...")
                    continue
            else:
                node_filter = filt
            print("模式: 1.简单测速  2.标准测试  5.快速测速")
            mode_choice = input("请选择 [1/2/5] (默认1): ").strip()
            fast9 = mode_choice == "5"
            mode9 = "normal" if mode_choice == "2" else "speed"
            urls = read_subscribe_urls()
            if not urls:
                print("[错误] 未找到 代理.txt")
                input("\n按 Enter 返回菜单...")
                continue
            urls = _select_subscribe_urls(urls)  # 多条订阅手动选择
            if not urls:
                continue  # 用户取消 → 回菜单
            print("\n排序方式：")
            print("  1. 订阅顺序")
            print("  2. 最大速度 降序 ⬅ 默认")
            print("  3. 最大速度 升序")
            print("  4. 平均速度 降序")
            print("  5. 平均速度 升序")
            print("  6. 节点名 A→Z")
            print("  7. 节点名 Z→A")
            sort_choice = input("请选择 [1-7] (默认2): ").strip()
            sort_map = {"1": "none", "2": "max_desc", "3": "max_asc",
                        "4": "avg_desc", "5": "avg_asc",
                        "6": "name_asc", "7": "name_desc"}
            sort_by = sort_map.get(sort_choice, "max_desc")
            st9 = load_settings()
            last_result_path = await run_test(urls, mode9, sort_by, fast=fast9,
                                              workers=st9.get("workers", DEFAULT_WORKERS),
                                              node_filter=node_filter, node_limit=node_limit,
                                              window_seconds=0 if fast9 else st9.get("speed_window_seconds", 0))
            if last_result_path and os.path.exists(last_result_path) and st9.get("auto_open_report", True):
                _open_report(last_result_path)
            input("\n按 Enter 返回菜单...")

        elif choice == "10":
            # 结果管理：列最近报告，编号打开 / D+编号删除
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
                    mode = ""
                    if base.startswith("测速结果_"):
                        mode = _MODE_NAMES.get(base[len("测速结果_"):].rsplit("_", 2)[0], "")
                    print(f"  {i:>2}. {mt} {_pad_right(mode, 10)} {base}")
                act = input("操作: ").strip().upper()
                if act:
                    try:
                        if act.startswith("D"):
                            idx = int(act[1:])
                            base, files = reports[idx - 1]
                            for f in files:
                                try:
                                    os.remove(os.path.join(OUTPUT_DIR, f))
                                except OSError:
                                    pass
                            print(f"[OK] 已删除: {base}（{len(files)} 个文件）")
                        else:
                            idx = int(act)
                            base, files = reports[idx - 1]
                            pngs = [f for f in files if f.endswith(".png")]
                            _open_report(os.path.join(OUTPUT_DIR, pngs[0] if pngs else files[0]))
                    except (ValueError, IndexError):
                        print("[错误] 无效编号")
            input("\n按 Enter 返回菜单...")

        elif choice == "11":
            # 订阅管理：查看（遮蔽）/ 添加 / 删除 / 打开文件编辑
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
                        if 0 <= idx < len(urls):
                            target = urls[idx]
                            # 菜单显示行（非空非注释）→ 原始行号映射；逐行原样保留（newline=""）
                            with open(SUBSCRIBE_FILE, "r", encoding="utf-8-sig", newline="") as fr:
                                raw_lines = fr.readlines()
                            clean_idx = [i for i, l in enumerate(raw_lines)
                                         if l.strip() and not l.strip().startswith("#")]
                            del_raw = clean_idx[idx]
                            rest_lines = [l for i, l in enumerate(raw_lines) if i != del_raw]
                            with open(SUBSCRIBE_FILE, "w", encoding="utf-8", newline="") as f:
                                f.write("".join(rest_lines))
                            print(f"[OK] 已删除第 {idx + 1} 条")
                            logger.info("订阅 URL 已删除",
                                        extra=_ev("manual_subscribe_input",
                                                  {"url": _mask_url(target), "deleted": True}))
                        else:
                            print("[错误] 编号超出范围")
                    except (ValueError, IndexError):
                        print("[错误] 无效编号")
                else:
                    print("[错误] 无效操作")

        elif choice == "12":
            # 设置：窗口秒数 / 并行数 / 自动打开报告 / 恢复默认（~/.airport_speedtest.json）
            print(_current_settings_line())
            print("操作: 1=测速窗口秒数  2=并行数  3=自动打开报告  4=恢复默认  回车=返回")
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
            except OSError as e:
                # 设置文件写失败（只读/权限/磁盘）不拖垮菜单
                print(f"[错误] 保存设置失败: {_safe_exc_str(e)}")
                logger.warning("保存设置失败: %s", _safe_exc_str(e))
            input("\n按 Enter 返回菜单...")

        elif choice == "13":
            # 环境信息：版本/依赖/mihomo/订阅/文件统计（标签列统一 16 显示宽对齐）
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

        elif choice == "5":
            # 优先打开本次会话生成的结果；否则回退扫描 output 目录最新 PNG
            target = last_result_path if last_result_path and os.path.exists(last_result_path) else ""
            if not target and os.path.exists(OUTPUT_DIR):
                pngs = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".png")]
                if pngs:
                    latest = max(pngs, key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)))
                    target = os.path.join(OUTPUT_DIR, latest)
            if target:
                _open_report(target)
            else:
                print("暂无结果文件")
            input("\n按 Enter 返回菜单...")

        elif choice == "6":
            # 版本对比：现有内核 mihomo -v vs 远程最新 tag（失败静默降级）
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
                    logger.info(f"mihomo 更新完成: {dst}",
                                extra=_ev("mihomo_update", {"ok": True, "path": dst,
                                                            "version": new_ver}))
                    print(f"[OK] 更新完成: {dst}" + (f" ({new_ver})" if new_ver else ""))
                else:
                    logger.error("mihomo 更新失败（下载或解压失败）",
                                 extra=_ev("mihomo_update", {"ok": False, "error": "download/unzip"}))
                    print("[错误] 更新失败")
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"mihomo 更新失败: {_safe_exc_str(e)}",
                             extra=_ev("mihomo_update", {"ok": False, "error": _safe_exc_str(e)[:200]}))
                print(f"[错误] 更新失败: {_safe_exc_str(e)}")
            input("\n按 Enter 返回菜单...")

        elif choice == "7":
            print("再见!")
            break

        else:
            if not choice:
                continue  # 空回车直接重绘菜单
            print("无效选择")
            logger.warning("无效菜单选择: %s", choice,
                           extra=_ev("invalid_input", {"choice": choice}))
            input("\n按 Enter 继续...")


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
    finally:
        _cleanup_empty_log()

__all__ = ['_MODE_NAMES', '_last_run_line', '_list_reports', '_append_subscribe_url',
           '_select_subscribe_urls', '_current_settings_line', '_open_report',
           'show_menu', 'async_main', 'main']
