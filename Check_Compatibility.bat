@echo off
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0app.py" compat
) else (
  python "%~dp0app.py" compat
)
pause
