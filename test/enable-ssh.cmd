@echo off
REM ---------------------------------------------------------------------------
REM  CowAgent-Rev - open the remote debug channel (OpenSSH Server) on this PC.
REM
REM  Double-click me. I self-elevate, then hand over to enable-ssh.ps1 which
REM  does the real work and prompts for the key to authorize. Safe to run more
REM  than once: every step checks its own state first.
REM
REM  What this opens: inbound TCP 22, PRIVATE network profile only - your home
REM  LAN. It is NOT reachable from the internet unless you separately forward
REM  port 22 on your router. Don't.
REM ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul 2>&1
title CowAgent-Rev  -  enable remote debug channel

REM Arguments are deliberately NOT forwarded through elevation: an SSH key
REM contains spaces, and surviving two layers of cmd + PowerShell quoting is
REM fragile. enable-ssh.ps1 prompts for it instead.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable-ssh.ps1"
echo.
pause
