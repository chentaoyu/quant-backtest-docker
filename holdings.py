"""持仓存储与导入。

持仓保存在 data/holdings.json，每只股票一条（同一只股票多笔买入按加权成本合并）。
导入支持从券商 App / Excel 复制的表格文本或 CSV：自动识别分隔符和常见中文表头。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime

import pandas as pd

from data_loader import CACHE_DIR
from stock_list import load_stock_list

HOLDINGS_FILE = CACHE_DIR / "holdings.json"
_LOCK = threading.Lock()

FIELDS = ("symbol", "name", "shares", "cost_price", "buy_date", "stop_loss_pct", "take_profit_pct", "strategy", "note")
HEADER_ALIASES = {
    "symbol": ("代码", "证券代码", "股票代码", "symbol", "code"),
    "name": ("名称", "证券名称", "股票名称", "股票", "name"),
    "shares": ("股数", "持仓", "持仓数量", "持股数", "持仓股数", "数量", "股票余额", "证券数量", "shares"),
    "cost_price": ("成本", "成本价", "参考成本", "参考成本价", "持仓成本", "摊薄成本", "买入均价", "cost", "cost_price"),
    "buy_date": ("买入日期", "建仓日期", "日期", "buy_date", "date"),
    "stop_loss_pct": ("止损", "止损%", "stop_loss", "stop_loss_pct"),
    "take_profit_pct": ("止盈", "止盈%", "take_profit", "take_profit_pct"),
    "note": ("备注", "note"),
}
POSITIONAL = ("symbol", "shares", "cost_price", "buy_date")


class HoldingError(ValueError):
    """持仓数据不合法。"""


# ---------------------------------------------------------------- 存储
def list_holdings() -> list[dict]:
    with _LOCK:
        return _read()


def _read() -> list[dict]:
    try:
        return json.loads(HOLDINGS_FILE.read_text(encoding="utf-8")).get("holdings", [])
    except (OSError, ValueError):
        return []


def _write(items: list[dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    items = sorted(items, key=lambda x: x["symbol"])
    payload = {"updated_at": datetime.now().isoformat(timespec="seconds"), "holdings": items}
    tmp = HOLDINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HOLDINGS_FILE)


def _names() -> dict[str, str]:
    stocks = load_stock_list()
    return {s["symbol"]: s["name"] for s in stocks["stocks"]} if stocks.get("source") != "local-cache" else {}


def normalize(raw: dict, names: dict[str, str] | None = None) -> dict:
    """校验并规整一条持仓，非法时抛 HoldingError。"""
    names = _names() if names is None else names
    symbol = normalize_symbol(raw.get("symbol"))
    if names and symbol not in names:
        raise HoldingError(f"股票代码不存在：{symbol}")
    try:
        shares = int(float(str(raw.get("shares", "")).replace(",", "")))
    except ValueError:
        raise HoldingError("股数必须是数字") from None
    if shares <= 0:
        raise HoldingError("股数需大于 0")
    cost = _number(raw.get("cost_price"), "成本价")
    if cost is None or cost <= 0:
        raise HoldingError("成本价需大于 0")
    item = {
        "symbol": symbol,
        "name": names.get(symbol) or str(raw.get("name") or "").strip() or symbol,
        "shares": shares,
        "cost_price": round(cost, 4),
        "buy_date": _date(raw.get("buy_date")),
        "stop_loss_pct": _pct(raw.get("stop_loss_pct"), "止损"),
        "take_profit_pct": _pct(raw.get("take_profit_pct"), "止盈"),
        "strategy": raw.get("strategy") or None,
        "note": str(raw.get("note") or "").strip()[:200],
    }
    return item


def normalize_symbol(value) -> str:
    """600519 / 600519.SH / SH600519 / 2241（Excel 吃掉前导 0）→ 6 位代码。"""
    match = re.search(r"\d{1,6}", str(value or ""))
    if not match:
        raise HoldingError(f"无法识别股票代码：{value}")
    return match.group().zfill(6)


def _number(value, label: str) -> float | None:
    if value is None or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").replace("¥", ""))
    except ValueError:
        raise HoldingError(f"{label}必须是数字：{value}") from None


def _pct(value, label: str) -> float | None:
    number = _number(value, label)
    if number is None:
        return None
    if not 0 < abs(number) < 100:
        raise HoldingError(f"{label}比例应在 0–100 之间")
    return abs(number)


def _date(value) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        day = pd.Timestamp(str(value).strip()).date()
    except (ValueError, TypeError):
        raise HoldingError(f"日期格式不正确：{value}") from None
    if day > datetime.now().date():
        raise HoldingError("买入日期不能晚于今天")
    return day.isoformat()


def _merge(old: dict, new: dict) -> dict:
    shares = old["shares"] + new["shares"]
    cost = (old["shares"] * old["cost_price"] + new["shares"] * new["cost_price"]) / shares
    dates = [d for d in (old.get("buy_date"), new.get("buy_date")) if d]
    return {**old, **{k: v for k, v in new.items() if v not in (None, "")},
            "shares": shares, "cost_price": round(cost, 4), "buy_date": min(dates) if dates else None}


def upsert(raw: dict) -> dict:
    item = normalize(raw)
    with _LOCK:
        items = [h for h in _read() if h["symbol"] != item["symbol"]]
        items.append(item)
        _write(items)
    return item


def delete(symbol: str) -> None:
    with _LOCK:
        items = _read()
        rest = [h for h in items if h["symbol"] != symbol]
        if len(rest) == len(items):
            raise HoldingError(f"持仓中没有 {symbol}")
        _write(rest)


# ---------------------------------------------------------------- 导入
def _split(line: str, sep: str | None) -> list[str]:
    cells = line.split(sep) if sep else line.split()
    return [c.strip().strip('"').strip() for c in cells]


def _header_map(cells: list[str]) -> dict[int, str] | None:
    mapping = {}
    for i, cell in enumerate(cells):
        key = cell.lower().replace(" ", "")
        for field, aliases in HEADER_ALIASES.items():
            if key in aliases and field not in mapping.values():
                mapping[i] = field
                break
    return mapping if "symbol" in mapping.values() else None


def parse_import(text: str) -> list[dict]:
    """把粘贴文本解析成预览行：[{line, ok, error, item | raw, merged}]。"""
    lines = [ln for ln in (text or "").replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        raise HoldingError("没有可导入的内容")
    sample = lines[0]
    sep = "\t" if "\t" in sample else ("," if "," in sample else ("，" if "，" in sample else None))

    header = _header_map(_split(lines[0], sep))
    if header is None and not re.search(r"\d", _split(lines[0], sep)[0]):
        raise HoldingError("没有识别到表头里的“代码”列；无表头时请按 代码,股数,成本[,买入日期] 的顺序")
    has_header = header is not None
    body = lines[1:] if has_header else lines
    header = header or dict(enumerate(POSITIONAL))

    names = _names()
    rows: list[dict] = []
    by_symbol: dict[str, dict] = {}
    for offset, line in enumerate(body, start=2 if has_header else 1):
        cells = _split(line, sep)
        raw = {field: cells[i] for i, field in header.items() if i < len(cells)}
        row = {"line": offset, "raw": raw, "ok": True, "error": None, "merged": False}
        try:
            item = normalize(raw, names)
        except HoldingError as exc:
            row.update(ok=False, error=str(exc))
            rows.append(row)
            continue
        if item["symbol"] in by_symbol:
            first = by_symbol[item["symbol"]]
            first["item"] = _merge(first["item"], item)
            first["merged"] = True
            row.update(ok=False, error=f"与第 {first['line']} 行同一股票，已合并（加权成本）")
        else:
            row["item"] = item
            by_symbol[item["symbol"]] = row
        rows.append(row)
    return rows


def commit_import(rows: list[dict], mode: str) -> list[dict]:
    if mode not in ("append", "replace"):
        raise HoldingError("导入模式只能是 append 或 replace")
    new = [r["item"] for r in rows if r["ok"]]
    if not new:
        raise HoldingError("没有可导入的有效行")
    with _LOCK:
        current = {} if mode == "replace" else {h["symbol"]: h for h in _read()}
        for item in new:
            current[item["symbol"]] = _merge(current[item["symbol"]], item) if item["symbol"] in current else item
        _write(list(current.values()))
        return _read()
