#!/usr/bin/env bash
# 新 ECS / 新机器一键部署：检查（可选安装）Docker → 准备 .env → 构建 → 启动 → 健康检查。
# 可重复执行：已存在的 .env 不会被覆盖，只更新显式传入的配置。
#
# 用法：
#   ./scripts/deploy-ecs.sh                     # 交互式
#   ./scripts/deploy-ecs.sh -y                  # 全自动
#   ./scripts/deploy-ecs.sh -y --port 8001
#   ./scripts/deploy-ecs.sh -y --token xxxxx    # 写入 .env（不想留在 shell 历史里就手动改 .env）
#   ./scripts/deploy-ecs.sh -y --cn-mirror      # 构建时使用国内 npm/pip 镜像源
#   ./scripts/deploy-ecs.sh -y --skip-build     # 已有镜像时跳过构建
#   ./scripts/deploy-ecs.sh --no-docker-install # 没装 Docker 时直接报错，不尝试安装
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT=""
TOKEN=""
ASSUME_YES=0
SKIP_BUILD=0
ALLOW_DOCKER_INSTALL=1
CN_MIRROR=0

usage() {
  cat <<'EOF'
用法: ./scripts/deploy-ecs.sh [选项]

  -y, --yes              不询问，直接执行
      --port <端口>      宿主机端口（写入 .env 的 PORT，默认 8000）
      --token <token>    写入 .env 的 TUSHARE_TOKEN
      --cn-mirror        构建时使用国内 npm/pip 镜像源
      --skip-build       跳过 docker compose build，直接用现有镜像启动
      --no-docker-install  本机没有 Docker 时直接报错，不尝试安装
  -h, --help             显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) ASSUME_YES=1 ;;
    --port)
      PORT="${2:-}"
      if [[ -z "$PORT" ]]; then echo "--port 需要一个端口号" >&2; exit 2; fi
      shift
      ;;
    --token)
      TOKEN="${2:-}"
      if [[ -z "$TOKEN" ]]; then echo "--token 需要一个值" >&2; exit 2; fi
      shift
      ;;
    --cn-mirror) CN_MIRROR=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --no-docker-install) ALLOW_DOCKER_INSTALL=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage; exit 2 ;;
  esac
  shift
done

confirm() {
  if [[ $ASSUME_YES -eq 1 ]]; then
    return 0
  fi
  read -r -p "$1 [y/N] " reply
  [[ "$reply" == "y" || "$reply" == "Y" ]]
}

SUDO=""

# ---------------------------------------------------------------- Docker
if ! command -v docker >/dev/null 2>&1; then
  if [[ $ALLOW_DOCKER_INSTALL -eq 0 ]]; then
    echo "未找到 docker，且指定了 --no-docker-install" >&2
    exit 1
  fi
  echo "未检测到 Docker。"
  if ! confirm "使用 https://get.docker.com 安装 Docker？"; then
    echo "已取消。请先安装 Docker 后重试。" >&2
    exit 1
  fi
  if [[ $EUID -ne 0 ]]; then
    SUDO="sudo"
  fi
  $SUDO sh -c 'curl -fsSL https://get.docker.com | sh'
  $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
  echo "Docker 安装完成。"
fi

if [[ $EUID -ne 0 ]] && ! docker info >/dev/null 2>&1; then
  SUDO="sudo"
fi

if ! $SUDO docker info >/dev/null 2>&1; then
  echo "无法访问 Docker daemon。请用 sudo 运行，或把当前用户加入 docker 组后重新登录：" >&2
  echo "  sudo usermod -aG docker \$USER" >&2
  exit 1
fi

# ---------------------------------------------------------------- Compose
if ! $SUDO docker compose version >/dev/null 2>&1; then
  echo "未找到 docker compose 插件，尝试安装..."
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -qq || true
    $SUDO apt-get install -y docker-compose-plugin || true
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y docker-compose-plugin || true
  fi
  if ! $SUDO docker compose version >/dev/null 2>&1; then
    echo "仍找不到 docker compose，请手动安装 Compose 插件后重试。" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------- .env
set_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" .env
    rm -f .env.bak
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
}

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已从 .env.example 创建 .env"
fi

if [[ -n "$PORT" ]]; then
  set_env PORT "$PORT"
fi
if [[ -n "$TOKEN" ]]; then
  set_env TUSHARE_TOKEN "$TOKEN"
fi
if [[ $CN_MIRROR -eq 1 ]]; then
  set_env NPM_REGISTRY "https://registry.npmmirror.com"
  set_env PIP_INDEX_URL "https://pypi.tuna.tsinghua.edu.cn/simple"
  echo "已切换 npm/pip 国内镜像源"
fi

if ! grep -Eq '^TUSHARE_TOKEN=.+' .env; then
  echo "提示：TUSHARE_TOKEN 为空，将自动回退到 akshare（免 token，首次取数较慢）。"
fi

# ---------------------------------------------------------------- 构建与启动
if [[ $SKIP_BUILD -eq 1 ]]; then
  echo "跳过构建，直接启动..."
  $SUDO docker compose up -d --no-build
else
  echo "开始构建并启动（首次需要几分钟）..."
  $SUDO docker compose up -d --build
fi

# ---------------------------------------------------------------- 健康检查
cid="$($SUDO docker compose ps -q web 2>/dev/null || true)"
if [[ -z "$cid" ]]; then
  echo "容器未创建，请查看：docker compose logs web" >&2
  exit 1
fi

status=""
for _ in $(seq 1 90); do
  status="$($SUDO docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)"
  if [[ "$status" == "healthy" || "$status" == "running" ]]; then
    break
  fi
  sleep 2
done

if [[ "$status" != "healthy" && "$status" != "running" ]]; then
  echo "健康检查未通过（当前状态：${status:-未知}），最近日志：" >&2
  $SUDO docker compose logs --tail=60 web >&2 || true
  exit 1
fi

HOST_PORT="$($SUDO docker compose port web 8000 2>/dev/null | awk -F: 'NR==1 {print $NF}')"
PUBLIC_IP="$(curl -fsS -m 3 https://api.ipify.org 2>/dev/null || true)"
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="127.0.0.1"
fi

cat <<EOF

部署完成：http://${PUBLIC_IP}:${HOST_PORT:-8000}

后续：
  查看日志    docker compose logs -f web
  重启        docker compose restart web
  停止        docker compose down          # 保留数据
  清空数据    docker compose down -v       # 删除行情缓存和报告

注意：
  1. 服务没有登录鉴权，请用安全组/防火墙限制来源 IP，不要直接暴露到公网。
  2. 行情缓存和报告在命名卷里；新机器首次回测会按需拉取数据。
  3. 修改 .env（如填 TUSHARE_TOKEN）后需要 docker compose up -d 重新创建容器。
EOF
