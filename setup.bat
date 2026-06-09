@echo off
REM ===  MonsterBox one-time setup  ===
REM Run this once. It installs MonsterBox and loads a couple of sample monsters.
title MonsterBox setup
cd /d "%~dp0"

echo.
echo Installing MonsterBox (this can take a minute the first time)...
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
py -m monsterbox --data "%~dp0data" seed --reset

echo.
echo  Setup complete.  Double-click  MonsterBox.bat  to launch.
echo.
pause
