@echo off
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0app.py" guard disarm
) else (
  python "%~dp0app.py" guard disarm
)
pause
