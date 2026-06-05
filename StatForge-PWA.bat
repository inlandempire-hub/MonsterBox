@echo off
REM ===  StatForge PWA (web build) — local test launcher  ===
REM Serves the static docs/ folder (the GitHub Pages build) on its OWN port,
REM separate from the desktop app, and opens it in a clean Chrome app-window.
REM
REM This is the SAME thing that will run on GitHub Pages — just served locally.
REM Storage is the browser's IndexedDB, so it's independent from the desktop app.
REM
REM Close the small "StatForge PWA server" window to stop it.
title StatForge PWA launcher
cd /d "%~dp0"

REM Static file server for the web build (port 8077 to stay clear of the
REM desktop app's 8000 and its service worker).
start "StatForge PWA server" /min py -m http.server 8077 --directory "%~dp0docs"

REM Give the server a moment to come up.
ping -n 2 127.0.0.1 >nul

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME%" (
  start "" "%CHROME%" --app=http://127.0.0.1:8077/ --start-maximized
) else (
  start "" "http://127.0.0.1:8077/"
)

exit /b 0
