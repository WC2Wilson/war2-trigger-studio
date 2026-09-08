@echo off
cd /d "%~dp0"
set PYTHONPATH=%CD%\src
where py >nul 2>nul
if not errorlevel 1 (
  py -3 src\documentation_tools.py
) else (
  python src\documentation_tools.py
)
if errorlevel 1 pause
