@echo off
chcp 65001 >nul
title 机场测速工具

set "DIR=%~dp0"
cd /d "%DIR%"

:: 检查 Python：只认 .exe（防止商店别名和 .cmd/.bat 垫片），python 不可用时回退 py -3
:: 同时校验版本 >= 3.9（代码用了 list[...] 等新语法注解）
set "PY="
for /f "delims=" %%i in ('where python 2^>nul') do if /i "%%~xi"==".exe" set "PY=python"
if defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if errorlevel 1 set "PY="
)
if not defined PY (
    for /f "delims=" %%i in ('where py 2^>nul') do if /i "%%~xi"==".exe" set "PY=py -3"
    if defined PY (
        py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
        if errorlevel 1 set "PY="
    )
)
if not defined PY goto :no_python

:: 检查依赖
%PY% -c "import aiohttp, yaml, PIL, tqdm, requests" >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装依赖（首次可能需要几分钟，请耐心等待）...
    %PY% -m pip install -r "core\requirements.txt"
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试；国内网络可尝试:
        echo   %PY% -m pip install -r core\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
    echo [OK] 依赖安装完成
)

%PY% "core\speed_test.py" %*
if errorlevel 1 pause
goto :eof

:no_python
echo [错误] 未找到 Python 3.9+（或版本过低），请安装 Python 3.9+ 并勾选 "Add python.exe to PATH"
pause
exit /b 1
