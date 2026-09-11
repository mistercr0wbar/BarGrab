@echo off
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe bargrab.py
) else (
  start "" pythonw bargrab.py
)
