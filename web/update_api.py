"""在线版本更新 API（方案 C：GHCR 镜像拉取式）。

与宿主机 updater（scripts/host-update.sh，由 systemd path unit 触发）通过
update-channel 通信目录协作：

- 容器写  update_request.json  → 宿主机 updater 读取后删除
- 宿主机写 update_status.json / update.log → 容器读取并在页面展示

镜像由 GitHub Actions（.github/workflows/release.yml）构建推送到 GHCR；
版本检测走 GitHub Releases API，进程内缓存 VERSION_CACHE_TTL 秒。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter()

GITHUB_REPO = os.environ.get("UPDATE_GITHUB_REPO", "chentaoyu/quant-backtest-docker")
GITHUB_API = "https://api.github.com"
UPDATE_MODE = os.environ.get("UPDATE_MODE", "none")  # none | host-updater
UPDATE_TOKEN = os.environ.get("UPDATE_TOKEN", "")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHANNEL_DIR = Path(os.environ.get("UPDATE_CHANNEL_DIR", _PROJECT_ROOT / "update-channel"))
REQUEST_FILE = CHANNEL_DIR / "update_request.json"
STATUS_FILE = CHANNEL_DIR / "update_status.json"
LOG_FILE = CHANNEL_DIR / "update.log"

VERSION_CACHE_TTL = 20 * 60  # 秒：GitHub 版本信息缓存
STALE_BUILD_SECONDS = 20 * 60  # building/restarting 超过该时长视为疑似卡死（允许重试）
LOG_TAIL_LINES = 200

_TAG_RE = re.compile(r"^v\d+(\.\d+){0,3}$")

_lock = threading.Lock()
_latest_cache: dict[str, Any] = {"data": None, "warning": None, "fetched_at": 0.0}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- GitHub API
def _github_get(path: str) -> Any:
    req = urllib.request.Request(
        GITHUB_API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "quant-backtest-updater",
        },
    )
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_latest_release() -> tuple[dict[str, Any] | None, str | None]:
    """最新正式 Release（GitHub 的 /releases/latest 已排除 draft/prerelease）。

    返回 (release, warning)；没有 Release 或网络失败时 release 为 None。
    """
    try:
        data = _github_get(f"/repos/{GITHUB_REPO}/releases/latest")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, "仓库还没有正式 Release：打一个 v* tag 触发 CI 构建后即可在线更新"
        return None, f"GitHub API HTTP {exc.code}"
    except Exception as exc:  # 网络错误、解析错误等
        return None, f"GitHub API 不可用：{exc}"
    if not isinstance(data, dict):
        return None, "GitHub API 返回格式异常"
    return data, None


def _latest_release_cached(force: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    with _lock:
        fresh = (
            _latest_cache["fetched_at"] > 0
            and time.monotonic() - _latest_cache["fetched_at"] < VERSION_CACHE_TTL
        )
        if not force and fresh:
            return _latest_cache["data"], _latest_cache["warning"]
    release, warning = _fetch_latest_release()
    with _lock:
        _latest_cache["data"] = release
        _latest_cache["warning"] = warning
        _latest_cache["fetched_at"] = time.monotonic()
    return release, warning


# ---------------------------------------------------------------- 状态文件
def _read_status() -> dict[str, Any] | None:
    try:
        data = json.loads(STATUS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _log_tail() -> str:
    try:
        lines = LOG_FILE.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


def _is_stale(data: dict[str, Any]) -> bool:
    if data.get("state") not in ("building", "restarting"):
        return False
    started = data.get("started_at")
    if not started:
        return True
    try:
        started_dt = datetime.fromisoformat(started)
        if started_dt.tzinfo is None:
            started_dt = started_dt.astimezone()  # 无时区后缀时按本地时间处理
        elapsed = (datetime.now().astimezone() - started_dt).total_seconds()
    except ValueError:
        return True
    return elapsed > STALE_BUILD_SECONDS


def _status_summary() -> dict[str, Any] | None:
    data = _read_status()
    if not data:
        return None
    return {
        "state": data.get("state", "idle"),
        "from_tag": data.get("from_tag"),
        "to_tag": data.get("to_tag"),
        "last_good_tag": data.get("last_good_tag"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "error": data.get("error"),
    }


# ---------------------------------------------------------------- 校验
def _require_token(provided: str | None) -> None:
    if not UPDATE_TOKEN:
        raise HTTPException(500, "服务器未配置 UPDATE_TOKEN，无法在线更新")
    if not provided or not secrets.compare_digest(provided, UPDATE_TOKEN):
        raise HTTPException(401, "更新令牌不正确")


def _require_updater_mode() -> None:
    if UPDATE_MODE != "host-updater":
        raise HTTPException(
            501,
            "当前部署未启用在线更新（UPDATE_MODE != host-updater）。"
            "手动更新：git pull && docker compose pull web && docker compose up -d",
        )


def _ensure_no_inflight() -> None:
    if REQUEST_FILE.exists():
        raise HTTPException(409, "已有更新请求待处理")
    data = _read_status() or {}
    if data.get("state") in ("building", "restarting") and not _is_stale(data):
        raise HTTPException(409, "更新正在进行中，请稍候")


def _write_request(payload: dict[str, Any]) -> None:
    CHANNEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REQUEST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    os.replace(tmp, REQUEST_FILE)


# ---------------------------------------------------------------- 接口
class UpdateTrigger(BaseModel):
    target_tag: str | None = None  # 缺省使用最新 Release 的 tag


@router.get("/api/version")
def get_version() -> dict:
    """当前版本 / 最新 Release / 是否有更新 / 最近一次更新状态。"""
    current_version = os.environ.get("APP_VERSION", "dev")
    current_commit = os.environ.get("APP_COMMIT", "unknown")
    release, warning = _latest_release_cached()
    latest: dict[str, Any] | None = None
    has_update: bool | None = None
    if release:
        tag = str(release.get("tag_name") or "")
        latest = {
            "tag": tag,
            "name": release.get("name") or tag,
            "published_at": release.get("published_at"),
            "html_url": release.get("html_url"),
            "notes": (release.get("body") or "")[:4000],
        }
        has_update = current_version != tag
    return {
        "current_version": current_version,
        "current_commit": current_commit,
        "latest": latest,
        "has_update": has_update,
        "update_mode": UPDATE_MODE,
        "warning": warning,
        "last_update": _status_summary(),
    }


@router.post("/api/update")
def trigger_update(
    payload: UpdateTrigger | None = None,
    x_update_token: str | None = Header(default=None),
) -> dict:
    """触发在线更新：写请求文件，由宿主机 updater 消费。"""
    _require_token(x_update_token)
    _require_updater_mode()
    _ensure_no_inflight()

    target = (payload.target_tag if payload and payload.target_tag else "").strip()
    if not target:
        release, _ = _latest_release_cached()
        target = str((release or {}).get("tag_name") or "")
    if not target:
        raise HTTPException(503, "无法确定目标版本（GitHub Release 信息不可用）")
    if not _TAG_RE.match(target):
        raise HTTPException(400, f"目标版本格式不合法：{target}")

    _write_request(
        {"type": "update", "to": target, "requested_at": _now_iso(), "by": "web"}
    )
    return {"triggered": True, "target": target}


@router.post("/api/rollback")
def trigger_rollback(x_update_token: str | None = Header(default=None)) -> dict:
    """回滚到最近一次成功更新的版本（last_good_tag）。"""
    _require_token(x_update_token)
    _require_updater_mode()
    _ensure_no_inflight()

    data = _read_status() or {}
    last_good = str(data.get("last_good_tag") or "")
    if not last_good:
        raise HTTPException(409, "还没有成功过一次在线更新，没有可回滚的版本")
    if not _TAG_RE.match(last_good):
        raise HTTPException(409, f"历史版本记录异常：{last_good}")

    _write_request(
        {"type": "rollback", "to": last_good, "requested_at": _now_iso(), "by": "web"}
    )
    return {"triggered": True, "target": last_good}


@router.get("/api/update/status")
def get_update_status() -> dict:
    """宿主机 updater 的状态 + 日志尾部。"""
    data = _read_status()
    if not data:
        return {"state": "idle", "mode": UPDATE_MODE, "log_tail": _log_tail()}
    out = dict(data)
    out["stale"] = _is_stale(data)
    out["log_tail"] = _log_tail()
    out["mode"] = UPDATE_MODE
    return out
