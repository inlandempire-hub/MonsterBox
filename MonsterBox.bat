@echo off
REM ===  MonsterBox launcher (PWA build)  ===
REM Double-click this (or the desktop shortcut to it) to start MonsterBox.
REM
REM MonsterBox is the same client-side PWA that runs on the web: the local app
REM and the web app are one and the same build (in docs\). Everything runs in
REM your browser and is stored locally (IndexedDB) — nothing uploaded.
REM
REM The local file server runs INVISIBLY (no console window) via "pyw"
REM (pythonw), and shuts itself down a few seconds after you close the app
REM window — the page sends a heartbeat while open and serve_local.py exits once
REM the heartbeats stop. Nothing is left running in the background.
title MonsterBox
cd /d "%~dp0"

REM Static file server for the PWA build, hidden (no console). Fixed port 8077
REM keeps the IndexedDB origin stable across launches so your library persists.
start "" pyw "%~dp0serve_local.py"

REM Give the server a moment to come up before opening the browser.
ping -n 2 127.0.0.1 >nul

REM Prefer a clean Chrome "app window" (no tabs/address bar — feels like a
REM desktop app). Fall back to the default browser otherwise.
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME%" (
  start "" "%CHROME%" --app=http://127.0.0.1:8077/ --start-maximized
) else (
  start "" "http://127.0.0.1:8077/"
)

exit /b 0
