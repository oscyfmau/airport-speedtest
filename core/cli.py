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
from .utils import *

def _open_report(path: str) -> bool:
    """打开报告文件（Windows os.startfile；macOS open；Linux xdg-open；失败不崩溃）"""
    try:
        if sys.platform == "win32":
            os.startfile(path)
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
                    skip_next = i + 1
                    try:
                        workers = max(1, min(int(args[i + 1]), MAX_WORKERS))
                    except ValueError:
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
            choice = input("\n请选择 [1-8]: ").strip()
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
                        try:
                            exists = os.path.exists(SUBSCRIBE_FILE)
                            saved = False
                            if exists:
                                with open(SUBSCRIBE_FILE, "r", encoding="utf-8-sig") as fr:
                                    lines = [l for l in fr]
                                if manual in [l.strip() for l in lines if l.strip()]:
                                    print("[信息] 该 URL 已在 代理.txt 中")
                                else:
                                    with open(SUBSCRIBE_FILE, "a", encoding="utf-8") as f:
                                        if lines and not lines[-1].endswith("\n"):
                                            f.write("\n")
                                        f.write(manual + "\n")
                                    print("[OK] 已保存到 代理.txt")
                                    saved = True
                            else:
                                with open(SUBSCRIBE_FILE, "w", encoding="utf-8") as f:
                                    f.write(manual + "\n")
                                print("[OK] 已保存到 代理.txt")
                                saved = True
                            if saved:
                                logger.info("订阅 URL 已保存到 代理.txt",
                                            extra=_ev("manual_subscribe_input",
                                                      {"url": _mask_url(manual), "saved": True}))
                        except Exception as e:
                            logger.warning("保存 代理.txt 失败: %s", _safe_exc_str(e))
                            print(f"[错误] 保存失败: {_safe_exc_str(e)}")
                else:
                    continue
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

            last_result_path = await run_test(urls, mode, sort_by, fast=fast)
            if last_result_path and os.path.exists(last_result_path):
                _open_report(last_result_path)
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
    except Exception:
        logger.exception("程序异常退出", extra=_ev("run_exception", {"phase": "main"}))
    finally:
        _cleanup_empty_log()

__all__ = ['_MODE_NAMES', '_last_run_line', '_open_report', 'show_menu', 'async_main', 'main']
