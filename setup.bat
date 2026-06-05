@echo off
REM ===  StatForge one-time setup  ===
REM Run this once. It installs StatForge and loads a couple of sample monsters.
title StatForge setup
cd /d "%~dp0"

echo.
echo Installing StatForge (this can take a minute the first time)...
echo.
py -m pip install -e ".[web]"
if errorlevel 1 (
  echo.
  echo  ^>^> Install failed. Make sure Python is installed from python.org
  echo     and that "py" works in a terminal.
  echo.
  pause
  exit /b 1
)

echo.
echo Loading sample monsters...
py -m statforge --data "%~dp0data" seed --reset

echo.
echo  Setup complete.  Double-click  StatForge.bat  to launch.
echo.
pause
