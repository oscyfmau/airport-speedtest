@echo off
chcp 65001 >nul
title 机场测速工具

set "DIR=%~dp0"
cd /d "%DIR%"

:: 检查 Python：python 不可用时回退 py -3 启动器
set "PY="
where python >nul 2>&1
if errorlevel 1 goto :try_py
python -c "import sys" >nul 2>&1
if errorlevel 1 goto :try_py
set "PY=python"
goto :check_deps

:try_py
where py >nul 2>&1
if errorlevel 1 goto :no_python
py -3 -c "import sys" >nul 2>&1
if errorlevel 1 goto :no_python
set "PY=py -3"

:check_deps
%PY% -c "import aiohttp, yaml, PIL, tqdm, requests" >nul 2>&1
if errorlevel 1 (
    echo [信息] 正在安装依赖...
    %PY% -m pip install -r "core\requirements.txt" -q
)

%PY% "core\speed_test.py" %*
if errorlevel 1 pause
goto :eof

:no_python
echo [错误] 未找到可用的 Python，请安装 Python 3.8+ 并勾选 "Add python.exe to PATH"
pause
exit /b 1