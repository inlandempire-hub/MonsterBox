@echo off
REM Double-click to start the MonsterBox backend (FastAPI) on http://127.0.0.1:8090
REM Close this window (or press Ctrl+C) to stop it.
cd /d "%~dp0"
echo Starting MonsterBox API on http://127.0.0.1:8090
echo (leave this window open while you use the app; close it to stop the server)
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8090
echo.
echo Server stopped.
pause
