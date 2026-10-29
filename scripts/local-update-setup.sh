#!/usr/bin/env bash
# 在本地 Mac 启用在线更新（等价于 ECS 上 deploy-ecs.sh 安装 systemd updater 的部分）。
#
#   1. 生成 UPDATE_TOKEN 写入 .env（已有则保留）
#   2. 设置 UPDATE_MODE=host-updater
#   3. 安装 launchd WatchPaths 代理（监听 update-channel/，等价 systemd path unit）
#   4. 把当前运行镜像固化到 .env 的 IMAGE_TAG，重建容器使新环境生效
#
# 可重复执行（幂等）。之后：GitHub 打新 tag → 页面红点 → 点击更新。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LABEL="com.quant-backtest.updater"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

get_env() { sed -n "s|^${1}=||p" .env 2>/dev/null | tail -1; }
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
}

echo "==> 项目目录：$ROOT"
mkdir -p "$ROOT/update-channel"

# 1. 更新令牌
if [[ -z "$(get_env UPDATE_TOKEN)" ]]; then
  set_env UPDATE_TOKEN "$(openssl rand -hex 16)"
  echo "✓ 已生成 UPDATE_TOKEN 并写入 .env"
else
  echo "✓ .env 已有 UPDATE_TOKEN，保留现有值"
fi

# 2. 更新模式
set_env UPDATE_MODE "host-updater"
echo "✓ UPDATE_MODE=host-updater"

# 3. 安装 launchd 监听（幂等：先卸载旧的再装）
UID_="$(id -u)"
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
sed "s|@ROOT@|$ROOT|g" scripts/quant-updater.mac.plist > "$PLIST"
launchctl bootstrap "gui/$UID_" "$PLIST"
echo "✓ 已安装并启动 launchd 更新监听"
echo "  plist: $PLIST"
echo "  （每次登录自动生效；触发日志：update-channel/launchd.log）"

# 4. 固化当前镜像 tag + 重建容器
if docker info >/dev/null 2>&1; then
  CUR_TAG="$(docker inspect quant-backtest-web-1 --format '{{.Config.Image}}' 2>/dev/null | sed -n 's|.*:||p' || true)"
  set_env IMAGE_TAG "${CUR_TAG:-latest}"
  echo "✓ IMAGE_TAG=${CUR_TAG:-latest}"
  if docker compose pull web >/dev/null 2>&1; then
    echo "✓ 镜像已就绪"
  else
    echo "• 镜像拉取失败（离线？），compose 将回退本地构建"
  fi
  docker compose up -d
  echo "✓ 容器已按新环境变量重建"
else
  echo "• Docker 未运行：稍后手动执行 docker compose up -d"
fi

echo
echo "完成！打开 http://127.0.0.1:8000 ，右上角版本徽章已是完整更新模式。"
echo "更新令牌（页面首次使用输入一次）：$(get_env UPDATE_TOKEN)"
echo "体验完整流程：git tag v0.3.1 && git push origin v0.3.1 → 页面出现红点 → 点击更新。"
