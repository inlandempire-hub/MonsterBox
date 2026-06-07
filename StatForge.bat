@echo off
REM ===  StatForge launcher (PWA build)  ===
REM Double-click this (or the desktop shortcut to it) to start StatForge.
REM
REM StatForge is now the same client-side PWA that runs on the web: the local
REM app and the web app are one and the same build (in docs\). Everything runs
REM in your browser and is stored locally (IndexedDB) — no Python server, no
REM Flask, nothing uploaded.
REM
REM This serves the docs\ folder on a fixed local port (8077) so the browser
REM treats it as a stable app origin (your compendium is tied to that origin),
REM and opens it in a clean Chrome app-window. Close the small "StatForge
REM server" window to stop it.
title StatForge
cd /d "%~dp0"

REM Static file server for the PWA build. Fixed port 8077 keeps the IndexedDB
REM origin stable across launches so your library persists.
start "StatForge server" /min py -m http.server 8077 --directory "%~dp0docs"

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
