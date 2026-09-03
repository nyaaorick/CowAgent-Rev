@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
title CowAgent-Rev

cd /d "%~dp0.."
set "ROOT=%CD%"
set "VENV=%ROOT%\.venv"
set "CFG=%ROOT%\config.json"

echo.
echo    ______                 ___                    __
echo   / ____/___ _      __   /   ^|  ____ ____  ____  / /_
echo  / /   / __ \ ^| /^| / /  / /^| ^| / __ `/ _ \/ __ \/ __/
echo / /___/ /_/ / ^|/ ^|/ /  / ___ ^|/ /_/ /  __/ / / / /_
echo \____/\____/^|__/^|__/  /_/  ^|_^|\__, /\___/_/ /_/\__/
echo                              /____/   Rev  -  WeChatFerry + GLM
echo.

REM ---------------------------------------------------------------- Python
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [X] No Python found. Install Python 3.10-3.13 from https://python.org
    echo     and TICK "Add python.exe to PATH" during setup.
    goto :fail
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo [1/5] Python %PYVER%  ^(%PY%^)

REM ----------------------------------------------------------- WeChatFerry
REM Vendored in this repo, so a plain clone or ZIP already has it. If it is
REM missing the checkout is incomplete -- say so rather than failing later.
if not exist "%ROOT%\WeChatFerry\clients\python\wcferry\client.py" (
    echo [X] WeChatFerry\clients\python is missing from this checkout.
    echo     It is vendored in this repo, so a normal clone should include it.
    echo     Try: git checkout -- WeChatFerry
    goto :fail
)
echo [2/5] WeChatFerry present ^(vendored^)

REM ----------------------------------------------------------------- venv
if not exist "%VENV%\Scripts\python.exe" (
    echo [3/5] Creating virtual environment ^(first run, takes a minute^)...
    %PY% -m venv "%VENV%"
    if errorlevel 1 ( echo [X] venv creation failed. & goto :fail )
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet
    echo       Installing dependencies...
    "%VENV%\Scripts\python.exe" -m pip install -r "%ROOT%\requirements.txt" --quiet
    if errorlevel 1 ( echo [X] Dependency install failed. & goto :fail )
) else (
    echo [3/5] Virtual environment ready
)

REM --------------------------------------------------------------- config
if not exist "%CFG%" (
    echo [4/5] No config.json yet - creating one from the template.
    copy /y "%~dp0config.example.json" "%CFG%" >nul
    echo.
    echo   ================================================================
    echo    ACTION NEEDED: paste your Zhipu GLM API key into config.json
    echo.
    echo      File:  %CFG%
    echo      Field: "zhipu_ai_api_key"
    echo      Key:   https://open.bigmodel.cn/usercenter/apikeys
    echo.
    echo    Then double-click this file again.
    echo   ================================================================
    echo.
    start "" notepad "%CFG%"
    goto :fail
)

"%VENV%\Scripts\python.exe" "%~dp0check_config.py"
if errorlevel 1 goto :fail
echo [4/5] Config OK

REM ---------------------------------------------------------------- start
echo [5/5] Starting CowAgent-Rev...
echo.
echo   Console:  http://127.0.0.1:9899
echo   Stop:     press Ctrl+C in this window
echo.
"%VENV%\Scripts\python.exe" "%ROOT%\app.py"
set "RC=%ERRORLEVEL%"
echo.
echo CowAgent-Rev exited with code %RC%.
pause
exit /b %RC%

:fail
echo.
pause
exit /b 1
