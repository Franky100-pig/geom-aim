#!/bin/bash
# GEOM AIM launcher for Linux
# Strategy: prefer a Python 3.10-3.13 that already has pygame; otherwise try to install.
# Avoid Python 3.14+ because pygame has no prebuilt wheels for it yet.
cd "$(dirname "$0")" || exit 1

CANDIDATES=(
  "python3.13"
  "python3.12"
  "python3.11"
  "python3.10"
  "python3"
  "python"
)

py_version_ok() {
  local py="$1"
  local ver
  ver=$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) || return 1
  case "$ver" in
    3.10|3.11|3.12|3.13) return 0 ;;
    *) return 1 ;;
  esac
}

PY=""
for c in "${CANDIDATES[@]}"; do
  [ -z "$c" ] && continue
  if command -v "$c" >/dev/null 2>&1 && py_version_ok "$c" && "$c" -c "import pygame" 2>/dev/null; then
    PY="$c"
    break
  fi
done

if [ -z "$PY" ]; then
  for c in "${CANDIDATES[@]}"; do
    [ -z "$c" ] && continue
    if command -v "$c" >/dev/null 2>&1 && py_version_ok "$c"; then
      echo "Found Python $c; installing dependencies..."
      if "$c" -m pip install -r requirements.txt --user; then
        PY="$c"
        break
      else
        echo "Failed to install with $c; trying next Python..."
      fi
    fi
  done
fi

if [ -z "$PY" ]; then
  echo "No usable Python 3.10-3.13 found. Cannot install pygame."
  echo "If your python3 is 3.14+, pygame does not provide prebuilt wheels yet."
  echo "Install Python 3.13 and run: python3.13 -m pip install -r requirements.txt"
  exit 1
fi

if ! "$PY" -c "import pygame" 2>/dev/null; then
  echo "Dependency check failed: $PY cannot import pygame"
  exit 1
fi

echo "Using Python: $PY"
exec "$PY" main.py
