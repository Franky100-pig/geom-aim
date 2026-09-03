#!/bin/bash
# 双击即可运行 GEOM AIM（macOS）
cd "$(dirname "$0")" || exit 1

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "没找到 python3，先装一个吧：https://www.python.org/downloads/"
  read -r -p "按回车关闭..."
  exit 1
fi

if ! "$PY" -c "import pygame" 2>/dev/null; then
  echo "缺少依赖，正在安装 requirements.txt..."
  "$PY" -m pip install -r requirements.txt
  if [ $? -ne 0 ]; then
    echo "安装失败，请手动运行：$PY -m pip install -r requirements.txt"
    read -r -p "按回车关闭..."
    exit 1
  fi
fi

exec "$PY" main.py
