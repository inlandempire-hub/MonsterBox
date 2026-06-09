@echo off
REM ===  MonsterBox-PWA.bat — kept for backwards compatibility  ===
REM The desktop app and the PWA are now the SAME build, so there is a single
REM launcher: MonsterBox.bat. This file just forwards to it.
cd /d "%~dp0"
call "%~dp0MonsterBox.bat"
