@echo off
chcp 65001 >nul
title 机场测速工具

set "DIR=%~dp0"
cd /d "%DIR%"

:: 检查 Python（找不到 python 时回退 py -3 启动器）
set "PY=python"
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    where py >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set "PY=py -3"
    ) else (
        echo [错误] 未找到 Python，请先安装 Python 3.8+（安装时勾选 Add to PATH）
        pause
        exit /b 1
    )
)

:: 检查依赖
%PY% -c "import aiohttp, yaml, PIL, tqdm, requests" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [信息] 正在安装依赖...
    %PY% -m pip install -r "core\requirements.txt" -q
)

:: 传参给 Python
%PY% "core\speed_test.py" %*
if %ERRORLEVEL% neq 0 (
    pause
)
