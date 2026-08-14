@echo off
chcp 65001 >nul
title 机场测速工具

set "DIR=%~dp0"
cd /d "%DIR%"

:: 检查 Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: 检查依赖
python -c "import aiohttp, yaml, PIL, tqdm, requests" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [信息] 正在安装依赖...
    pip install -r "core\requirements.txt" -q
)

:: 传参给 Python
python "core\speed_test.py" %*
if %ERRORLEVEL% neq 0 (
    pause
)
