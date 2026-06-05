@echo off
REM ===  StatForge launcher  ===
REM Double-click this (or a desktop shortcut to it) to start StatForge.
REM
REM The web server runs invisibly (no console window) via "pyw" (pythonw), and
REM shuts itself down a few seconds after you close the app window/tab — the
REM page sends a heartbeat while open, and the server's idle watchdog exits once
REM the heartbeats stop (see: serve --shutdown-on-idle).
title StatForge
cd /d "%~dp0"

REM Start the local server with NO console window. It self-closes ~12s after the
REM app is closed.
start "" pyw -m statforge --data "%~dp0data" serve --port 8000 --shutdown-on-idle 12

REM Give the server a moment to come up before opening the browser.
REM (ping is a portable ~2s sleep; timeout fails if input is redirected)
ping -n 3 127.0.0.1 >nul

REM Prefer a clean Chrome "app window" (no tabs/address bar - feels like a
REM desktop app, opens maximized). Fall back to the default browser otherwise.
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME%" (
  start "" "%CHROME%" --app=http://127.0.0.1:8000 --start-maximized
) else (
  start "" "http://127.0.0.1:8000"
)

exit /b 0
