@echo off
REM GEOM AIM launcher for Windows
REM Strategy: prefer a Python 3.10-3.13 that already has pygame; otherwise try to install.
REM Avoid Python 3.14+ because pygame has no prebuilt wheels for it yet.
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY="

REM 1. Try versioned py launcher first (most reliable on Windows)
for %%V in (3.13 3.12 3.11 3.10) do (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -%%V -c "import sys; exit(0 if sys.version_info[:2] == tuple(map(int, '%%V'.split('.'))) else 1)" >nul 2>nul
    if not errorlevel 1 (
      py -%%V -c "import pygame" >nul 2>nul
      if not errorlevel 1 (
        set "PY=py -%%V"
        goto :found
      )
    )
  )
)

REM 2. Try generic python / python3 commands from PATH
for %%C in (python3 python) do (
  where %%C >nul 2>nul
  if not errorlevel 1 (
    %%C -c "import sys; v=sys.version_info[:2]; exit(0 if (3,10)<=v<=(3,13) else 1)" >nul 2>nul
    if not errorlevel 1 (
      %%C -c "import pygame" >nul 2>nul
      if not errorlevel 1 (
        set "PY=%%C"
        goto :found
      )
    )
  )
)

REM 3. No pygame found: try to install into a usable Python 3.10-3.13
for %%V in (3.13 3.12 3.11 3.10) do (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -%%V -c "import sys; exit(0 if sys.version_info[:2] == tuple(map(int, '%%V'.split('.'))) else 1)" >nul 2>nul
    if not errorlevel 1 (
      echo Python %%V found. Installing dependencies...
      py -%%V -m pip install -r requirements.txt
      if not errorlevel 1 (
        set "PY=py -%%V"
        goto :found
      ) else (
        echo Install failed for Python %%V.
      )
    )
  )
)

for %%C in (python3 python) do (
  where %%C >nul 2>nul
  if not errorlevel 1 (
    %%C -c "import sys; v=sys.version_info[:2]; exit(0 if (3,10)<=v<=(3,13) else 1)" >nul 2>nul
    if not errorlevel 1 (
      echo Installing dependencies into %%C...
      %%C -m pip install -r requirements.txt
      if not errorlevel 1 (
        set "PY=%%C"
        goto :found
      )
    )
  )
)

echo No usable Python 3.10-3.13 found. Cannot install pygame.
echo If your python is 3.14+, pygame does not provide prebuilt wheels yet.
echo Install Python 3.13 from https://www.python.org/downloads/ and try again.
pause
exit /b 1

:found
echo Using Python: %PY%
%PY% main.py
pause
