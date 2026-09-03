#!/bin/bash
# 双击即可运行 GEOM AIM（macOS）
# 策略：优先找已经装好 pygame 的 Python 3.10-3.13；没有则尝试安装；避开 3.14+（pygame 暂无 wheel，会源码编译失败）
cd "$(dirname "$0")" || exit 1

# 候选解释器：先查常见具体路径，再查版本化命令，最后回退 PATH
CANDIDATES=(
  "/Users/franky100/.workbuddy/binaries/python/envs/default/bin/python3"
  "/usr/local/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
  "python3.13"
  "python3.12"
  "python3.11"
  "python3.10"
  "python3"
  "python"
)

# 检查某 Python 版本是否在 3.10-3.13 之间（pygame wheel 稳定支持）
py_version_ok() {
  local py="$1"
  local ver
  ver=$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) || return 1
  case "$ver" in
    3.10|3.11|3.12|3.13) return 0 ;;
    *) return 1 ;;
  esac
}

# 1. 找已经能 import pygame 的 Python
PY=""
for c in "${CANDIDATES[@]}"; do
  [ -z "$c" ] && continue
  if command -v "$c" >/dev/null 2>&1 && py_version_ok "$c" && "$c" -c "import pygame" 2>/dev/null; then
    PY="$c"
    break
  fi
done

# 2. 没找到就挑一个可用的 3.10-3.13，尝试安装 pygame
if [ -z "$PY" ]; then
  for c in "${CANDIDATES[@]}"; do
    [ -z "$c" ] && continue
    if command -v "$c" >/dev/null 2>&1 && py_version_ok "$c"; then
      echo "找到 Python $c，正在安装依赖..."
      if "$c" -m pip install -r requirements.txt; then
        PY="$c"
        break
      else
        echo "用 $c 安装依赖失败，尝试下一个 Python..."
      fi
    fi
  done
fi

# 3. 还是没找到，给出明确提示
if [ -z "$PY" ]; then
  echo "没有可用的 Python 3.10-3.13 环境，无法安装 pygame。"
  echo "当前系统里的 python3 可能是 Python 3.14+，pygame 还没有对应的预编译包。"
  echo ""
  echo "解决方案（选其一）："
  echo "1. 安装 Python 3.13：https://www.python.org/downloads/release/python-3133/"
  echo "2. 在终端里用下面命令手动安装到指定 Python："
  echo "   /usr/local/bin/python3 -m pip install -r requirements.txt"
  echo "3. 然后用该 Python 直接启动："
  echo "   /usr/local/bin/python3 main.py"
  read -r -p "按回车关闭..."
  exit 1
fi

# 最终校验
if ! "$PY" -c "import pygame" 2>/dev/null; then
  echo "依赖校验失败：$PY 仍无法 import pygame"
  read -r -p "按回车关闭..."
  exit 1
fi

echo "使用 Python: $PY"
exec "$PY" main.py
