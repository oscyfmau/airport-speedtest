#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布打包脚本：生成仅含运行核心文件的精简 zip（供 GitHub Release 资产使用）。

用法：python tools/pack_release.py
产物：dist/airport-speedtest-v{VERSION}.zip（zip 内顶层目录与 zip 同名）

内容清单（改动只改 FILES / CORE_INCLUDE / DOCS_INCLUDE）：
- run.bat / 代理.txt.example / core/（全部 .py + requirements.txt）/ docs/（README×2/CHANGELOG/LICENSE/preview_report.png）
不含：bin/（首次运行自动下载）、.github/、output/、log/、代理.txt（敏感）、tools/
"""
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 顶层单文件
FILES = [
    "run.bat",
    "代理.txt.example",
]
# core/ 下包含的文件（目录整体递归时按前缀过滤）
CORE_INCLUDE = [".py", "requirements.txt"]
# docs/ 下包含的文件
DOCS_INCLUDE = [
    "README.md",
    "README_EN.md",
    "CHANGELOG.md",
    "LICENSE",
    "preview_report.png",
]


def get_version() -> str:
    """从 core/config.py 正则提取 VERSION（不 import，避免依赖环境）。"""
    src = (ROOT / "core" / "config.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', src, re.MULTILINE)
    if not m:
        sys.exit("ERROR: core/config.py 中未找到 VERSION")
    return m.group(1)


def collect() -> list:
    """返回 [(源路径, zip 内相对路径)] 清单，按目录顺序稳定输出。"""
    items = []
    for name in FILES:
        p = ROOT / name
        if not p.is_file():
            sys.exit(f"ERROR: 缺少文件 {p}")
        items.append((p, name))
    # core/：全部 .py + requirements.txt，跳过 __pycache__
    core_dir = ROOT / "core"
    if not core_dir.is_dir():
        sys.exit("ERROR: 缺少目录 core/")
    for p in sorted(core_dir.iterdir()):
        if p.is_dir() and p.name == "__pycache__":
            continue
        if p.is_file() and any(p.name.endswith(sfx) or p.name == sfx for sfx in CORE_INCLUDE):
            items.append((p, f"core/{p.name}"))
    # docs/：白名单
    docs_dir = ROOT / "docs"
    for name in DOCS_INCLUDE:
        p = docs_dir / name
        if not p.is_file():
            sys.exit(f"ERROR: 缺少文件 {p}")
        items.append((p, f"docs/{name}"))
    return items


def main() -> None:
    version = get_version()
    top = f"airport-speedtest-v{version}"
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    out_zip = out_dir / f"{top}.zip"

    items = collect()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, rel in items:
            zf.write(src, f"{top}/{rel}")

    total = out_zip.stat().st_size
    print(f"OK: {out_zip} ({total:,} bytes, {len(items)} files)")
    print(f"顶层目录: {top}/")
    for _, rel in items:
        print(f"  {rel}")


if __name__ == "__main__":
    main()
