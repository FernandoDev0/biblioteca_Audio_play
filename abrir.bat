@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Nao achei o Python do projeto em .venv
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m app
if errorlevel 1 pause
