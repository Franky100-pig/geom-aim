#!/bin/bash
# 双击即可运行 GEOM AIM（macOS）
cd "$(dirname "$0")" || exit 1

PY="/Users/franky100/.workbuddy/binaries/python/envs/default/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
  echo "没找到 python3，先装一个吧：https://www.python.org/downloads/"
  read -r -p "按回车关闭..."
  exit 1
fi

exec "$PY" main.py
