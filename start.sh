#!/bin/bash
# GEOM AIM launcher for Linux
cd "$(dirname "$0")" || exit 1

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "Python 3 not found."
  echo "Install: sudo apt install python3 python3-pip   # Debian/Ubuntu"
  echo "        sudo dnf install python3 python3-pip   # Fedora"
  exit 1
fi

if ! "$PY" -c "import pygame" 2>/dev/null; then
  echo "pygame missing. Installing from requirements.txt (--user)..."
  "$PY" -m pip install -r requirements.txt --user
  if [ $? -ne 0 ]; then
    echo "Install failed. Run manually: $PY -m pip install -r requirements.txt"
    exit 1
  fi
fi

exec "$PY" main.py
