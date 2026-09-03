@echo off
REM GEOM AIM launcher for Windows
setlocal
cd /d "%~dp0"

REM Locate a Python interpreter
set "PY="
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py"
)
if not defined PY (
  echo Python not found. Download from https://www.python.org/downloads/
  echo During install, tick "Add Python to PATH".
  pause
  exit /b 1
)

REM Install dependencies if missing
%PY% -c "import pygame" >nul 2>nul
if errorlevel 1 (
  echo Missing dependencies. Installing from requirements.txt...
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Install failed. Run manually: %PY% -m pip install -r requirements.txt
    pause
    exit /b 1
  )
)

%PY% main.py
pause
