"""自选股：关注列表与每只股票的策略设置。

策略设置三档：
- strategy 为空：自动，用体检选出的主策略和参数
- strategy 指定、params 为空：指定策略，参数用体检优化值（没体检则用默认值）
- strategy 指定、params 非空：指定策略 + 手动参数
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from types import SimpleNamespace

from data_loader import CACHE_DIR
from holdings import HoldingError, _names, normalize_symbol
from strategies import STRATEGIES

WATCHLIST_FILE = CACHE_DIR / "watchlist.json"
DEFAULT_GROUP = "默认"
_LOCK = threading.Lock()


def _read() -> list[dict]:
    try:
        return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []


def _write(items: list[dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), "items": items}
    tmp = WATCHLIST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(WATCHLIST_FILE)


def list_items() -> list[dict]:
    with _LOCK:
        return _read()


def check_params(strategy: str | None, params: dict | None) -> dict | None:
    """校验手动参数：只接受策略声明过的参数，并检查约束。"""
    if strategy is None:
        return None
    if strategy not in STRATEGIES:
        raise HoldingError(f"未知策略：{strategy}")
    if not params:
        return None
    cls = STRATEGIES[strategy]
    spec = {p["name"]: p for p in cls.param_spec}
    result = {p["name"]: p["default"] for p in cls.param_spec}
    for name, value in params.items():
        if name not in spec:
            raise HoldingError(f"{cls.label}没有参数 {name}")
        number = float(value)
        if not spec[name]["min"] <= number <= spec[name]["max"]:
            raise HoldingError(f"{spec[name]['label']} 应在 {spec[name]['min']}–{spec[name]['max']} 之间")
        result[name] = int(number) if isinstance(spec[name]["default"], int) else number
    constraint = getattr(cls, "constraint", None)
    if constraint and not constraint(SimpleNamespace(**result)):
        raise HoldingError(f"参数不满足{cls.label}的约束：{result}")
    return result


def upsert(raw: dict) -> dict:
    symbol = normalize_symbol(raw.get("symbol"))
    names = _names()
    if names and symbol not in names:
        raise HoldingError(f"股票代码不存在：{symbol}")
    strategy = raw.get("strategy") or None
    with _LOCK:
        items = _read()
        old = next((i for i in items if i["symbol"] == symbol), None)
        item = {
            "symbol": symbol,
            "name": names.get(symbol) or (old or {}).get("name") or symbol,
            "group": (raw.get("group") or (old or {}).get("group") or DEFAULT_GROUP).strip()[:20],
            "strategy": strategy,
            "params": check_params(strategy, raw.get("params")),
            "note": str(raw.get("note") or "").strip()[:200],
            "added_at": (old or {}).get("added_at") or datetime.now().isoformat(timespec="seconds"),
        }
        items = [i for i in items if i["symbol"] != symbol] + [item]
        _write(items)
    return item


def add_many(text: str, group: str | None = None) -> dict:
    """粘贴代码列表批量加入；已在自选里的跳过。"""
    codes = list(dict.fromkeys(re.findall(r"\d{1,6}", text or "")))
    if not codes:
        raise HoldingError("没有识别到股票代码")
    names = _names()
    added, skipped, invalid = [], [], []
    with _LOCK:
        items = _read()
        existing = {i["symbol"] for i in items}
        for code in codes:
            symbol = code.zfill(6)
            if names and symbol not in names:
                invalid.append(symbol)
            elif symbol in existing:
                skipped.append(symbol)
            else:
                items.append({"symbol": symbol, "name": names.get(symbol, symbol),
                              "group": (group or DEFAULT_GROUP).strip()[:20], "strategy": None, "params": None,
                              "note": "", "added_at": datetime.now().isoformat(timespec="seconds")})
                existing.add(symbol)
                added.append(symbol)
        _write(items)
    return {"added": added, "skipped": skipped, "invalid": invalid}


def delete(symbol: str) -> None:
    with _LOCK:
        items = _read()
        rest = [i for i in items if i["symbol"] != symbol]
        if len(rest) == len(items):
            raise HoldingError(f"自选中没有 {symbol}")
        _write(rest)
