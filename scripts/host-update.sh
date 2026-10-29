#!/usr/bin/env bash
# quant-backtest 宿主机在线更新执行器（方案 C：GHCR 镜像拉取式）。
#
# 由 systemd path unit（scripts/quant-updater.path）在
# update-channel/update_request.json 出现时触发，也可手动执行。
#
# 流程：
#   1. 读取请求（type: update | rollback，to: 目标镜像 tag）
#   2. git 同步到目标 tag 对应的提交（更新 compose/脚本；不做本地构建）
#   3. 改写 .env 的 IMAGE_TAG → docker compose pull web（失败即止，容器不动）
#   4. docker compose up -d --wait（替换容器并等待 healthy）
#   5. 新版本不健康时自动回滚：IMAGE_TAG 回 last_good_tag 再 pull + up
#
# 状态写入 update-channel/update_status.json，日志追加 update.log。

# ---------------------------------------------------------------- 自我保护
# git reset 会替换本脚本文件；把自身复制到 /tmp 执行，避免"运行中的脚本被换"。
if [[ "${BASH_SOURCE[0]}" != "/tmp/quant-updater-run.sh" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  cp "${BASH_SOURCE[0]}" /tmp/quant-updater-run.sh
  exec env QUANT_ROOT="$ROOT" bash /tmp/quant-updater-run.sh
fi
set -euo pipefail
ROOT="${QUANT_ROOT:?}"
cd "$ROOT"

CHANNEL="$ROOT/update-channel"
REQ="$CHANNEL/update_request.json"
STATUS="$CHANNEL/update_status.json"
LOG="$CHANNEL/update.log"

# docker 定位：launchd（macOS）/精简 PATH 环境里 docker 常不在 PATH，主动补查常见位置
if ! command -v docker >/dev/null 2>&1; then
  for _d in /usr/local/bin /opt/homebrew/bin; do
    if [[ -x "$_d/docker" ]]; then PATH="$_d:$PATH"; break; fi
  done
fi
SUDO=""
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 || SUDO="sudo"

# GNU date 支持 -Is，macOS BSD date 不支持，用通用格式（Python fromisoformat 兼容两种）
now() { date +%Y-%m-%dT%H:%M:%S%z; }
log() { echo "[$(now)] $*" | tee -a "$LOG"; }

# 日志瘦身：超过 1MB 只保留后半
if [[ -f "$LOG" ]] && (( $(wc -c < "$LOG") > 1048576 )); then
  tail -c 524288 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

write_status() {
  # 参数：state from to lastgood started error
  ST="$1" FROM="${2:-}" TO="${3:-}" LG="${4:-}" SA="${5:-}" ERR="${6:-}" \
  STATUS_PATH="$STATUS" python3 - <<'PY'
import datetime
import json
import os

state = os.environ["ST"]
finished = None
if state in ("done", "failed", "rolled_back", "idle"):
    finished = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
doc = {
    "state": state,
    "from_tag": os.environ.get("FROM") or None,
    "to_tag": os.environ.get("TO") or None,
    "last_good_tag": os.environ.get("LG") or None,
    "started_at": os.environ.get("SA") or None,
    "finished_at": finished,
    "error": os.environ.get("ERR") or None,
}
path = os.environ["STATUS_PATH"]
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)
os.replace(tmp, path)
PY
}

fail() {
  write_status failed "$FROM_TAG" "$TO_TAG" "$LASTGOOD" "$STARTED" "$*"
  log "更新失败：$*"
  rm -f "$REQ"
  exit 1
}

set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
}

get_env() {
  sed -n "s/^${1}=//p" .env 2>/dev/null | tail -1
}

# ---------------------------------------------------------------- 并发保护
# Linux 用 flock；macOS 无 flock 时用 mkdir 原子锁（进程被杀由下面的陈旧清理兜底）
if command -v flock >/dev/null 2>&1; then
  exec 9>/tmp/quant-updater.lock
  if ! flock -n 9; then
    log "已有另一个更新实例在运行，退出"
    exit 0
  fi
else
  LOCKDIR="/tmp/quant-updater.lockdir"
  if ! mkdir "$LOCKDIR" 2>/dev/null; then
    if [[ -n "$(find "$LOCKDIR" -maxdepth 0 -mmin +40 2>/dev/null)" ]]; then
      log "发现陈旧锁（超过 40 分钟），清理后接管"
      rm -rf "$LOCKDIR"
      mkdir "$LOCKDIR" 2>/dev/null || { log "获取锁失败，退出"; exit 0; }
    else
      log "已有另一个更新实例在运行，退出"
      exit 0
    fi
  fi
  trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
fi

# ---------------------------------------------------------------- 读取请求
[[ -f "$REQ" ]] || exit 0
command -v python3 >/dev/null 2>&1 || { log "宿主机缺少 python3，无法执行更新"; exit 1; }

REQ_DATA=$(python3 -c "import json;print(json.dumps(json.load(open('$REQ'))))" 2>>"$LOG") \
  || { log "请求文件损坏，删除"; rm -f "$REQ"; exit 1; }
TYPE=$(python3 -c "import json;print(json.load(open('$REQ')).get('type',''))")
TO_TAG=$(python3 -c "import json;print(json.load(open('$REQ')).get('to') or '')")
rm -f "$REQ"  # 立即消费，避免重启后重复触发

FROM_TAG="$(get_env IMAGE_TAG)"
[[ -z "$FROM_TAG" ]] && FROM_TAG="latest"

LASTGOOD="$(python3 -c "
import json, os
try:
    d = json.load(open('$STATUS'))
    print(d.get('last_good_tag') or '')
except Exception:
    print('')
" 2>/dev/null || true)"
[[ -z "$LASTGOOD" ]] && LASTGOOD="$FROM_TAG"

if [[ "$TYPE" == "rollback" ]]; then
  # 回滚目标优先用请求里的 to，其次 last_good
  [[ -z "$TO_TAG" ]] && TO_TAG="$LASTGOOD"
  if [[ "$TO_TAG" == "$FROM_TAG" ]]; then
    write_status idle "$FROM_TAG" "" "$LASTGOOD" "" "当前就是 $FROM_TAG，无需回滚"
    exit 0
  fi
elif [[ "$TYPE" != "update" ]]; then
  write_status idle "$FROM_TAG" "" "$LASTGOOD" "" "未知请求类型：$TYPE"
  exit 1
fi

if ! [[ "$TO_TAG" =~ ^v[0-9]+(\.[0-9]+){0,3}$ ]]; then
  write_status failed "$FROM_TAG" "$TO_TAG" "$LASTGOOD" "" "非法目标 tag：$TO_TAG"
  log "非法目标 tag：$TO_TAG"
  exit 1
fi

STARTED="$(now)"
write_status building "$FROM_TAG" "$TO_TAG" "$LASTGOOD" "$STARTED"
log "===== 开始 $TYPE：$FROM_TAG → $TO_TAG（last_good=$LASTGOOD） ====="

# ---------------------------------------------------------------- git 同步到目标 tag
# 镜像和部署文件（compose/脚本）来自同一个 tag，保持严格对齐。
# 保护开发机（Mac 本地更新）：工作区有未提交改动时中止，避免 git reset --hard 吞掉 WIP。
# ECS 部署机是干净 clone，此检查恒通过。
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  fail "本地仓库有未提交改动，为避免丢失已中止（容器仍是 $FROM_TAG）；请先 commit 或 stash 后重试"
fi
if git fetch origin --tags --prune >>"$LOG" 2>&1; then
  if git rev-parse -q --verify "refs/tags/$TO_TAG" >/dev/null 2>&1; then
    if git reset --hard "refs/tags/$TO_TAG" >>"$LOG" 2>&1; then
      log "已同步部署文件到 $TO_TAG"
    else
      log "警告：git reset 失败，沿用现有部署文件"
    fi
  else
    log "警告：git 中找不到 tag $TO_TAG，沿用现有部署文件"
  fi
else
  log "警告：git fetch 失败（网络？），沿用现有部署文件"
fi

# ---------------------------------------------------------------- 拉镜像 + 换容器
set_env IMAGE_TAG "$TO_TAG"

if ! $SUDO docker compose pull web >>"$LOG" 2>&1; then
  set_env IMAGE_TAG "$FROM_TAG"
  fail "镜像拉取失败（服务未受影响，容器仍是 $FROM_TAG）"
fi

log "镜像拉取完成，替换容器并等待健康检查…"
if $SUDO docker compose up -d --wait --wait-timeout 300 >>"$LOG" 2>&1; then
  write_status done "$FROM_TAG" "$TO_TAG" "$TO_TAG" "$STARTED"
  log "更新完成：$FROM_TAG → $TO_TAG（last_good 已更新为 $TO_TAG）"
  exit 0
fi

# ---------------------------------------------------------------- 新版本起不来 → 自动回滚
log "新容器未通过健康检查，自动回滚到 $LASTGOOD …"
set_env IMAGE_TAG "$LASTGOOD"
$SUDO docker compose pull web >>"$LOG" 2>&1 || log "回滚镜像拉取失败（尝试用本地缓存）"
if $SUDO docker compose up -d --wait --wait-timeout 300 >>"$LOG" 2>&1; then
  write_status rolled_back "$FROM_TAG" "$TO_TAG" "$LASTGOOD" "$STARTED" \
    "新版本 $TO_TAG 启动失败，已自动回滚到 $LASTGOOD"
  log "已回滚到 $LASTGOOD"
else
  write_status failed "$FROM_TAG" "$TO_TAG" "$LASTGOOD" "$STARTED" \
    "新版本启动失败且回滚到 $LASTGOOD 也失败，请人工检查：docker compose logs web"
  log "回滚失败！请人工介入：docker compose logs web / 检查 .env 的 IMAGE_TAG"
fi
