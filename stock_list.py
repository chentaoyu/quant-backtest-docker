"""A 股股票列表（代码 + 名称），本地缓存。

首次调用会用 akshare 拉取全市场列表（约 5000+ 只），写入
`data/stock_list.json`，之后 7 天内直接读缓存；网络失败时回退到
本地已有行情缓存的标的。
"""
from __future__ import annotations

import contextlib
import io
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from data_loader import available_symbols

STOCK_LIST_FILE = Path(__file__).parent / "data" / "stock_list.json"
MAX_AGE = timedelta(days=7)
_LOCK = threading.Lock()


def exchange_of(symbol: str) -> str:
    if symbol.startswith(("60", "68", "90")):
        return "SH"
    if symbol.startswith(("00", "30", "20")):
        return "SZ"
    return "BJ"


def _normalize(stocks: list[dict]) -> list[dict]:
    cleaned = []
    for item in stocks:
        symbol = str(item.get("symbol", "")).strip()
        name = str(item.get("name", "")).strip()
        if len(symbol) != 6 or not symbol.isdigit() or not name:
            continue
        cleaned.append({"symbol": symbol, "name": name, "exchange": item.get("exchange") or exchange_of(symbol)})
    cleaned.sort(key=lambda x: x["symbol"])
    return cleaned


def _fetch_from_akshare() -> list[dict]:
    import akshare as ak

    # akshare 内部会打进度条，Web 端不需要
    with contextlib.redirect_stderr(io.StringIO()):
        df = ak.stock_info_a_code_name()
    rows = []
    for code, name in zip(df["code"].tolist(), df["name"].tolist()):
        symbol = str(code).strip().zfill(6)
        rows.append({"symbol": symbol, "name": str(name).replace(" ", "").strip(), "exchange": exchange_of(symbol)})
    stocks = _normalize(rows)
    if not stocks:
        raise RuntimeError("akshare 返回的股票列表为空")
    return stocks


def _read_cache() -> dict | None:
    if not STOCK_LIST_FILE.exists():
        return None
    try:
        payload = json.loads(STOCK_LIST_FILE.read_text(encoding="utf-8"))
        stocks = _normalize(payload.get("stocks") or [])
        if not stocks:
            return None
        return {
            "stocks": stocks,
            "fetched_at": payload.get("fetched_at"),
            "source": payload.get("source") or "cache",
            "count": len(stocks),
        }
    except (OSError, ValueError):
        return None


def _write_cache(stocks: list[dict], fetched_at: str) -> None:
    STOCK_LIST_FILE.parent.mkdir(exist_ok=True)
    payload = {"fetched_at": fetched_at, "source": "akshare", "count": len(stocks), "stocks": stocks}
    tmp = STOCK_LIST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STOCK_LIST_FILE)


def _is_fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        return datetime.now() - datetime.fromisoformat(fetched_at) < MAX_AGE
    except ValueError:
        return False


def _fallback() -> dict:
    stocks = [
        {"symbol": s["symbol"], "name": s["symbol"], "exchange": exchange_of(s["symbol"])}
        for s in available_symbols()
    ]
    return {
        "stocks": stocks,
        "fetched_at": None,
        "source": "local-cache",
        "count": len(stocks),
        "warning": "股票列表拉取失败，暂时只能选择本地已有行情缓存的标的",
    }


def load_stock_list(refresh: bool = False) -> dict:
    with _LOCK:
        cached = _read_cache()
        if cached and not refresh and _is_fresh(cached["fetched_at"]):
            return {**cached, "warning": None}

        try:
            stocks = _fetch_from_akshare()
        except Exception as exc:  # noqa: BLE001 - 网络/接口异常都走降级
            if cached:
                return {
                    **cached,
                    "warning": f"股票列表更新失败，继续使用 {cached['fetched_at'] or '旧'} 的缓存：{exc}",
                }
            fallback = _fallback()
            fallback["warning"] = f"{fallback['warning']}（{exc}）"
            return fallback

        fetched_at = datetime.now().isoformat(timespec="seconds")
        _write_cache(stocks, fetched_at)
        return {
            "stocks": stocks,
            "fetched_at": fetched_at,
            "source": "akshare",
            "count": len(stocks),
            "warning": None,
        }
