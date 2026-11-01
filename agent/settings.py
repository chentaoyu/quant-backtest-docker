"""Agent 运行时配置：.env 提供默认值，页面修改后存 data/agent/settings.json 并立即生效（页面设置优先）。"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SETTINGS_FILE = Path(os.getenv("AGENT_SETTINGS", Path(__file__).resolve().parents[1] / "data" / "agent" / "settings.json"))

# 盯盘规则 -> 页面展示名（用于逐条开关）
RULES = {
    "limit_up": "涨停", "limit_down": "跌停", "move_up": "大涨", "move_down": "大跌",
    "stop_loss": "触及止损线", "take_profit": "达到止盈线", "cost_break": "跌破成本价", "cost_regain": "回到成本价上方",
    "signal": "将触发策略信号", "index_drop": "指数大跌", "index_rise": "指数大涨",
    "breadth_down": "市场普跌", "limit_down_wave": "跌停潮",
}


class LLMSettings(BaseModel):
    base_url: str = Field(default_factory=lambda: os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1"))
    api_key: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY", "ollama"))
    main: str = Field(default_factory=lambda: os.getenv("LLM_MAIN", "qwen3.5:35b-a3b-nvfp4"))
    fast: str = Field(default_factory=lambda: os.getenv("LLM_FAST", "qwen3.5:4b"))
    reasoning: Literal["none", "low", "medium", "high"] = Field(
        default_factory=lambda: os.getenv("LLM_REASONING", "none"))
    timeout: float = Field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT", "300")), ge=10, le=1800)


class MonitorSettings(BaseModel):
    enabled: bool = Field(default_factory=lambda: os.getenv("MONITOR_ENABLED", "1") == "1")
    interval: int = Field(default_factory=lambda: int(os.getenv("MONITOR_INTERVAL", "60")), ge=15, le=3600)
    llm_note: bool = Field(default_factory=lambda: os.getenv("MONITOR_LLM_NOTE", "1") == "1")
    # 解读默认用主模型：调用量小（每轮几条），实测 4b 容易把策略名脑补成指标结论
    note_model: Literal["main", "fast"] = Field(default_factory=lambda: os.getenv("MONITOR_NOTE_MODEL", "main"))
    index_warn: float = Field(-2.0, le=0, description="指数跌幅达到即「注意」（%）")
    index_alert: float = Field(-3.0, le=0, description="指数跌幅达到即「告警」（%）")
    index_up: float = Field(2.0, ge=0, description="指数涨幅达到即「提示」（%）")
    breadth_warn: float = Field(0.8, gt=0, le=1, description="下跌家数占比达到即「普跌」")
    limit_down_alert: int = Field(50, ge=1, description="跌停家数达到即「跌停潮」")
    move_warn: float = Field(0.5, gt=0, le=1, description="个股涨跌幅达到涨跌停幅度的比例 →「注意」")
    move_alert: float = Field(0.8, gt=0, le=1, description="个股涨跌幅达到涨跌停幅度的比例 →「告警」")
    disabled_rules: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)


_lock = threading.Lock()
_cache: Settings | None = None


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        out[key] = _deep_merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _overrides() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get() -> Settings:
    global _cache
    with _lock:
        if _cache is None:
            _cache = Settings(**_deep_merge(Settings().model_dump(), _overrides()))
        return _cache


def update(patch: dict) -> Settings:
    """合并校验后落盘；只保存与 .env 默认值不同的项，改 .env 仍能生效于未在页面改过的项。"""
    global _cache
    new = Settings(**_deep_merge(get().model_dump(), patch))  # 校验失败抛 ValidationError
    defaults = Settings().model_dump()
    diff = {sec: {k: v for k, v in vals.items() if defaults[sec].get(k) != v}
            for sec, vals in new.model_dump().items()}
    with _lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps({k: v for k, v in diff.items() if v}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        _cache = new
    return new


def reset() -> Settings:
    global _cache
    with _lock:
        SETTINGS_FILE.unlink(missing_ok=True)
        _cache = None
    return get()


def public() -> dict:
    """给页面看的配置：不回传 API Key 明文。"""
    data = get().model_dump()
    key = data["llm"].pop("api_key")
    data["llm"]["api_key_set"] = bool(key) and key != "ollama"
    data["rules"] = RULES
    data["overridden"] = {sec: sorted(vals) for sec, vals in _overrides().items()}
    return data
