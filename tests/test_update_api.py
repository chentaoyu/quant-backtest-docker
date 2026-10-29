import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.update_api as upd


@pytest.fixture(autouse=True)
def channel(tmp_path, monkeypatch):
    """把通信目录指向临时目录，并启用 host-updater 模式 + 固定令牌。"""
    monkeypatch.setattr(upd, "CHANNEL_DIR", tmp_path)
    monkeypatch.setattr(upd, "REQUEST_FILE", tmp_path / "update_request.json")
    monkeypatch.setattr(upd, "STATUS_FILE", tmp_path / "update_status.json")
    monkeypatch.setattr(upd, "LOG_FILE", tmp_path / "update.log")
    monkeypatch.setattr(upd, "UPDATE_MODE", "host-updater")
    monkeypatch.setattr(upd, "UPDATE_TOKEN", "secret-token")
    return tmp_path


def fake_release(tag="v0.3.1"):
    return {
        "tag_name": tag,
        "name": f"release {tag}",
        "published_at": "2026-10-29T00:00:00Z",
        "html_url": f"https://github.com/x/y/releases/tag/{tag}",
        "body": "release notes",
    }


def patch_latest(monkeypatch, release, warning=None):
    """注入新鲜的版本缓存，避免测试触网。"""
    monkeypatch.setattr(
        upd, "_latest_cache", {"data": release, "warning": warning, "fetched_at": time.monotonic()}
    )


def old_started(hours=1):
    return (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")


# ---------------------------------------------------------------- /api/version
def test_version_reports_current_and_latest(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v0.3.0")
    monkeypatch.setenv("APP_COMMIT", "abc1234def")
    patch_latest(monkeypatch, fake_release("v0.3.1"))
    data = upd.get_version()
    assert data["current_version"] == "v0.3.0"
    assert data["current_commit"] == "abc1234def"
    assert data["latest"]["tag"] == "v0.3.1"
    assert data["has_update"] is True
    assert data["update_mode"] == "host-updater"


def test_version_up_to_date(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v0.3.1")
    patch_latest(monkeypatch, fake_release("v0.3.1"))
    assert upd.get_version()["has_update"] is False


def test_version_no_release(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v0.3.0")
    patch_latest(monkeypatch, None, warning="还没有 Release")
    data = upd.get_version()
    assert data["latest"] is None
    assert data["has_update"] is None
    assert data["warning"] == "还没有 Release"


# ---------------------------------------------------------------- /api/update
def test_trigger_update_requires_token():
    with pytest.raises(HTTPException) as exc:
        upd.trigger_update(None, None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        upd.trigger_update(None, "wrong-token")
    assert exc.value.status_code == 401


def test_trigger_update_requires_updater_mode(monkeypatch):
    monkeypatch.setattr(upd, "UPDATE_MODE", "none")
    with pytest.raises(HTTPException) as exc:
        upd.trigger_update(None, "secret-token")
    assert exc.value.status_code == 501


def test_trigger_update_writes_request(monkeypatch):
    patch_latest(monkeypatch, fake_release("v0.3.1"))
    result = upd.trigger_update(None, "secret-token")
    assert result == {"triggered": True, "target": "v0.3.1"}
    req = json.loads(upd.REQUEST_FILE.read_text("utf-8"))
    assert req["type"] == "update"
    assert req["to"] == "v0.3.1"
    assert req["by"] == "web"


def test_trigger_update_rejects_bad_tag():
    with pytest.raises(HTTPException) as exc:
        upd.trigger_update(upd.UpdateTrigger(target_tag="v0.3.1; rm -rf /"), "secret-token")
    assert exc.value.status_code == 400


def test_trigger_update_conflict_when_request_pending():
    upd.REQUEST_FILE.write_text("{}", "utf-8")
    with pytest.raises(HTTPException) as exc:
        upd.trigger_update(None, "secret-token")
    assert exc.value.status_code == 409


def test_trigger_update_conflict_when_building():
    upd.STATUS_FILE.write_text(json.dumps({"state": "building", "started_at": upd._now_iso()}), "utf-8")
    with pytest.raises(HTTPException) as exc:
        upd.trigger_update(None, "secret-token")
    assert exc.value.status_code == 409


def test_stale_building_allows_retry(monkeypatch):
    upd.STATUS_FILE.write_text(json.dumps({"state": "building", "started_at": old_started()}), "utf-8")
    patch_latest(monkeypatch, fake_release("v0.3.1"))
    assert upd.trigger_update(None, "secret-token")["triggered"] is True


# ---------------------------------------------------------------- /api/rollback
def test_rollback_needs_last_good():
    with pytest.raises(HTTPException) as exc:
        upd.trigger_rollback("secret-token")
    assert exc.value.status_code == 409


def test_rollback_writes_request():
    upd.STATUS_FILE.write_text(json.dumps({"state": "done", "last_good_tag": "v0.3.0"}), "utf-8")
    result = upd.trigger_rollback("secret-token")
    assert result == {"triggered": True, "target": "v0.3.0"}
    req = json.loads(upd.REQUEST_FILE.read_text("utf-8"))
    assert req["type"] == "rollback"
    assert req["to"] == "v0.3.0"


# ---------------------------------------------------------------- /api/update/status
def test_status_idle_and_log_tail():
    upd.LOG_FILE.write_text("line1\nline2\n", "utf-8")
    data = upd.get_update_status()
    assert data["state"] == "idle"
    assert "line2" in data["log_tail"]
    assert data["mode"] == "host-updater"


def test_status_stale_detection():
    upd.STATUS_FILE.write_text(json.dumps({"state": "building", "started_at": old_started()}), "utf-8")
    assert upd.get_update_status()["stale"] is True

    upd.STATUS_FILE.write_text(json.dumps({"state": "building", "started_at": upd._now_iso()}), "utf-8")
    assert upd.get_update_status()["stale"] is False

    upd.STATUS_FILE.write_text(json.dumps({"state": "done", "started_at": old_started()}), "utf-8")
    assert upd.get_update_status()["stale"] is False
