#!/usr/bin/env bash
# 本地启动 Web 回测台。
# - 优先读取项目 .env
# - .env 没有 TUSHARE_TOKEN 时，从交互式 zsh 的 ~/.zshrc 取一次（不打印 token）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ -z "${TUSHARE_TOKEN:-}" && -f "$HOME/.zshrc" ]]; then
  # .zshrc 只对交互式 zsh 生效；用 -i 取 token，用标记避免启动横幅混入
  token="$(zsh -ic 'print -rn -- "__QB_TUSHARE__${TUSHARE_TOKEN:-}__END__"' 2>/dev/null \
    | sed -n 's/.*__QB_TUSHARE__\(.*\)__END__.*/\1/p' | tail -n 1 || true)"
  if [[ -n "$token" ]]; then
    export TUSHARE_TOKEN="$token"
  fi
fi

exec "$PYTHON" -m uvicorn web.app:app --host "$HOST" --port "$PORT"
