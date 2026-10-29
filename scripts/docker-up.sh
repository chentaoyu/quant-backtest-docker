#!/usr/bin/env bash
# 一键构建并启动：./scripts/docker-up.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已创建 .env（默认不填 token，会回退到 akshare）"
  echo "如需 Tushare，请编辑 .env 填入 TUSHARE_TOKEN 后重新运行本脚本。"
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "未找到 docker compose，请先安装 Docker Desktop 或 Compose 插件。" >&2
  exit 1
fi

docker compose up -d --build
docker compose ps

HOST_PORT="$(docker compose port web 8000 | awk -F: 'NR==1 {print $NF}')"
echo
echo "启动完成：http://127.0.0.1:${HOST_PORT:-8000}"
echo "查看日志：docker compose logs -f web"
