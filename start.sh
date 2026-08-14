#!/usr/bin/env bash
# 报价单提取比价工具 · 一键启动 Web UI
# 用法：./start.sh  （macOS 也可双击「启动工具.command」）
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "首次运行，正在创建 Python 环境..."
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev,web,ocr]"
fi

if [ ! -d web/node_modules ]; then
  echo "首次运行，正在安装前端依赖..."
  (cd web && npm install --no-audit --no-fund)
fi

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "提示：未设置 DEEPSEEK_API_KEY，真实文件解析不可用；可先在页面里跑「演示样本」。"
fi

echo "启动中：前端 + 后端（按 Ctrl+C 停止）"
cd web && exec npm run dev
