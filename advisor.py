"""持仓建议：策略体检（选出每只股票该信的策略）+ 每日操作建议 + K 线数据。

体检（较慢，按月做）：最近 5 年上做滚动验证（训练 3 年 / 测试 1 年），6 个策略各自
在训练段网格优化、在测试段跑样本外，按样本外夏普选主策略；再用最近 3 年优化出实盘参数。
建议（每天收盘后）：主策略的"状态 × 今日信号" + 止损止盈 + 明日触发价 + 6 策略共识。
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from backtesting import Backtest

from backtest_engine import (
    DEFAULT_CASH,
    DEFAULT_COMMISSION,
    BacktestError,
    _default_params,
    _optimize,
    _params_from_stats,
    _walk_forward_windows,
)
from data_loader import CACHE_DIR, last_session_close, load_daily
from holdings import list_holdings
from signals import latest_signal, trigger_prices
from strategies import STRATEGIES

CHECKUP_FILE = CACHE_DIR / "checkups.json"
CHECKUP_YEARS = 5
TRAIN_YEARS = 3
TEST_YEARS = 1
CHECKUP_MAX_AGE = timedelta(days=30)
SIGNAL_YEARS = 3
MIN_OOS_TRADES = 2
_LOCK = threading.Lock()

ADVICE = {
    "STOP_LOSS": ("止损", "error"),
    "TAKE_PROFIT": ("止盈", "warning"),
    "SELL": ("卖出", "error"),
    "BUY": ("买入/加仓", "success"),
    "HOLD": ("继续持有", "processing"),
    "WAIT": ("策略已离场", "warning"),
    "NO_STRATEGY": ("无有效策略", "default"),
    "UNCHECKED": ("待体检", "default"),
}


def _years_ago(years: int, extra_days: int = 0) -> str:
    return (datetime.now() - timedelta(days=365 * years + extra_days)).strftime("%Y%m%d")


def _bt(df: pd.DataFrame, cls) -> Backtest:
    return Backtest(df, cls, cash=DEFAULT_CASH, commission=DEFAULT_COMMISSION,
                    trade_on_close=False, exclusive_orders=True, finalize_trades=True)


def _finite(value, digits: int = 3):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, digits) if math.isfinite(value) else None


# ---------------------------------------------------------------- 体检
def _read_checkups() -> dict:
    try:
        return json.loads(CHECKUP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_checkups() -> dict:
    with _LOCK:
        return _read_checkups()


def _save_checkup(symbol: str, result: dict) -> None:
    with _LOCK:
        data = _read_checkups()
        data[symbol] = result
        CACHE_DIR.mkdir(exist_ok=True)
        CHECKUP_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _checkup_strategy(df: pd.DataFrame, cls, windows: list[dict]) -> dict:
    returns, trades, bh = [], 0, []
    for w in windows:
        train_start, test_start, test_end = (pd.Timestamp(w[k]) for k in ("train_start", "test_start", "test_end"))
        train = df.loc[train_start : test_start - pd.Timedelta(days=1)]
        if len(train) < 250:
            continue
        try:
            params = _params_from_stats(_optimize(_bt(train, cls), cls, {}), cls)
        except BacktestError:
            params = _default_params(cls)
        # 测试段连同训练段一起跑，指标有预热、持仓可跨窗口延续；只统计测试段的日收益
        stats = _bt(df.loc[train_start:test_end], cls).run(**params)
        equity = stats._equity_curve["Equity"]
        returns.append(equity.pct_change().loc[test_start:test_end].dropna())
        entries = stats._trades["EntryTime"]
        trades += int(((entries >= test_start) & (entries <= test_end)).sum())
        close = df["Close"].loc[test_start:test_end]
        if len(close) > 1:
            bh.append(close.iloc[-1] / df["Close"].loc[: test_start - pd.Timedelta(days=1)].iloc[-1] - 1)
    if not returns:
        raise BacktestError("数据不足，无法做滚动验证")

    daily = pd.concat(returns)
    curve = (1 + daily).cumprod()
    std = daily.std()
    sharpe = daily.mean() / std * np.sqrt(252) if std > 0 else None
    live = df.loc[pd.Timestamp(_years_ago(TRAIN_YEARS)) :]
    try:
        live_params = _params_from_stats(_optimize(_bt(live, cls), cls, {}), cls)
    except BacktestError:
        live_params = _default_params(cls)
    return {
        "oos_sharpe": _finite(sharpe),
        "oos_return_pct": _finite((curve.iloc[-1] - 1) * 100, 2),
        "oos_max_dd_pct": _finite((curve / curve.cummax() - 1).min() * 100, 2),
        "oos_trades": trades,
        "bh_return_pct": _finite((np.prod([1 + r for r in bh]) - 1) * 100, 2) if bh else None,
        "live_params": live_params,
        "error": None,
    }


def checkup(symbol: str) -> dict:
    df = load_daily(symbol, start=_years_ago(CHECKUP_YEARS, 10))
    windows = _walk_forward_windows(df.index[0].strftime("%Y%m%d"), df.index[-1].strftime("%Y%m%d"),
                                    TRAIN_YEARS, TEST_YEARS)
    strategies = {}
    for name, cls in STRATEGIES.items():
        try:
            strategies[name] = _checkup_strategy(df, cls, windows)
        except BacktestError as exc:
            strategies[name] = {"error": str(exc), "oos_sharpe": None, "live_params": _default_params(cls)}

    candidates = [
        (s["oos_sharpe"], name) for name, s in strategies.items()
        if s.get("oos_sharpe") is not None and s["oos_sharpe"] > 0 and s.get("oos_trades", 0) >= MIN_OOS_TRADES
    ]
    result = {
        "symbol": symbol,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "data_end": df.index[-1].date().isoformat(),
        "windows": windows,
        "best": max(candidates)[1] if candidates else None,
        "strategies": strategies,
    }
    _save_checkup(symbol, result)
    return result


# ---------------------------------------------------------------- 后台任务
class Jobs:
    """单线程后台体检队列：运行中再提交的股票追加到队尾。"""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._avg_sec = 7.0  # 单只体检耗时的滑动估计，用于前端倒计时

    def _snapshot(self, job: dict | None) -> dict | None:
        if job is None:
            return None
        with self._lock:
            started = job.get("current_started")
            return {
                **{k: v for k, v in job.items() if k != "current_started"},
                "symbols": list(job["symbols"]),
                "errors": dict(job["errors"]),
                "pending": job["symbols"][job["done"]:],
                "avg_sec": round(self._avg_sec, 1),
                "current_elapsed": round(time.time() - started, 1) if started else 0,
            }

    def get(self, job_id: str) -> dict | None:
        return self._snapshot(self._jobs.get(job_id))

    def running(self) -> dict | None:
        return self._snapshot(self._running())

    def _running(self) -> dict | None:
        return next((j for j in self._jobs.values() if j["status"] == "running"), None)

    def start_checkup(self, symbols: list[str]) -> dict:
        with self._lock:
            job = self._running()
            if job:
                pending = job["symbols"][job["done"]:]
                job["symbols"] += [s for s in dict.fromkeys(symbols) if s not in pending]
                job["total"] = len(job["symbols"])
            else:
                job = {"id": uuid.uuid4().hex[:8], "status": "running", "symbols": list(dict.fromkeys(symbols)),
                       "done": 0, "current": None, "current_started": None, "errors": {},
                       "started_at": datetime.now().isoformat(timespec="seconds")}
                job["total"] = len(job["symbols"])
                self._jobs = {job["id"]: job}
                threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return self._snapshot(job)

    def _run(self, job: dict) -> None:
        while True:
            with self._lock:
                if job["done"] >= len(job["symbols"]):
                    job.update(status="done", current=None, current_started=None,
                               finished_at=datetime.now().isoformat(timespec="seconds"))
                    return
                symbol = job["symbols"][job["done"]]
                job.update(current=symbol, current_started=time.time())
            started = time.time()
            try:
                checkup(symbol)
            except Exception as exc:  # noqa: BLE001 - 单只失败不影响其他
                job["errors"][symbol] = str(exc)
            with self._lock:
                self._avg_sec = self._avg_sec * 0.5 + (time.time() - started) * 0.5
                job["done"] += 1


jobs = Jobs()


def stale_symbols(force: bool = False) -> list[str]:
    checkups = load_checkups()
    result = []
    for h in list_holdings():
        c = checkups.get(h["symbol"])
        if force or not c or datetime.now() - datetime.fromisoformat(c["checked_at"]) > CHECKUP_MAX_AGE:
            result.append(h["symbol"])
    return result


# ---------------------------------------------------------------- 每日建议
def _strategy_params(name: str, check: dict | None) -> dict:
    live = ((check or {}).get("strategies", {}).get(name) or {}).get("live_params")
    return live or _default_params(STRATEGIES[name])


def _since_buy(df: pd.DataFrame, buy_date: str, trades: list[dict]) -> dict | None:
    """买入以来：一直持有的收益/最大回撤，以及若按主策略第一次卖出信号离场的结果。"""
    after = df["Close"].loc[pd.Timestamp(buy_date) :]
    if len(after) < 2:
        return None
    base = after.iloc[0]
    curve = after / base
    first_exit = next((t for t in trades if t["exit_date"] and t["exit_date"] > buy_date), None)
    return {
        "hold_return_pct": _finite((curve.iloc[-1] - 1) * 100, 2),
        "max_dd_pct": _finite((curve / curve.cummax() - 1).min() * 100, 2),
        "first_exit": None if first_exit is None else {
            "date": first_exit["exit_date"],
            "price": first_exit["exit_price"],
            "return_pct": _finite((first_exit["exit_price"] / base - 1) * 100, 2),
        },
    }


def _advice(holding: dict, pnl_pct: float, main: dict | None, checked: bool) -> tuple[str, str]:
    stop, take = holding.get("stop_loss_pct"), holding.get("take_profit_pct")
    if stop and pnl_pct <= -stop:
        return "STOP_LOSS", f"浮亏 {pnl_pct:.2f}% 已达止损线 -{stop}%"
    if take and pnl_pct >= take:
        return "TAKE_PROFIT", f"浮盈 {pnl_pct:.2f}% 已达止盈线 +{take}%"
    if main is None:
        if not checked:
            return "UNCHECKED", "还没做策略体检，先点“策略体检”"
        return "NO_STRATEGY", "近 5 年没有样本外有效的策略，只按止损止盈管理"
    label = main["label"]
    if main["action"] == "SELL":
        return "SELL", f"{label}今日收盘触发卖出，次日开盘执行"
    if main["action"] == "BUY":
        return "BUY", f"{label}今日收盘触发入场，可考虑加仓"
    if main["hold"]:
        return "HOLD", f"{label}自 {main['since'] or '—'} 起持有中，未触发离场"
    return "WAIT", f"{label}已于 {main['since'] or '—'} 离场，你的持仓与策略不一致，可减仓或等待买回信号"


def analyze_holding(holding: dict, check: dict | None) -> dict:
    symbol = holding["symbol"]
    start = min(_years_ago(SIGNAL_YEARS), (holding.get("buy_date") or "9999").replace("-", ""))
    df = load_daily(symbol, start=start)
    meta = df.attrs.get("meta") or {}
    signal_df = df.loc[pd.Timestamp(_years_ago(SIGNAL_YEARS)) :]

    close, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    shares, cost = holding["shares"], holding["cost_price"]
    pnl_pct = (close / cost - 1) * 100

    strategies, main = [], None
    best = holding.get("strategy") or (check or {}).get("best")
    for name, cls in STRATEGIES.items():
        params = _strategy_params(name, check)
        sig = latest_signal(signal_df, cls, params)
        row = {
            "name": name,
            "label": getattr(cls, "label", name),
            "params": params,
            "oos_sharpe": ((check or {}).get("strategies", {}).get(name) or {}).get("oos_sharpe"),
            **{k: sig[k] for k in ("action", "hold", "hold_after", "since")},
        }
        if name == best:
            row["trades"] = sig["trades"]
            row["triggers"] = trigger_prices(signal_df, symbol, cls, params, row["hold_after"])
            main = row
        strategies.append(row)

    code, reason = _advice(holding, pnl_pct, main, check is not None)
    bulls = sum(1 for s in strategies if s["hold_after"])
    return {
        **holding,
        "data_date": df.index[-1].date().isoformat(),
        "close": round(close, 3),
        "prev_close": round(prev, 3),
        "change_pct": _finite((close / prev - 1) * 100, 2),
        "market_value": round(close * shares, 2),
        "pnl": round((close - cost) * shares, 2),
        "pnl_pct": _finite(pnl_pct, 2),
        "day_pnl": round((close - prev) * shares, 2),
        "advice": {"code": code, "label": ADVICE[code][0], "color": ADVICE[code][1], "reason": reason},
        "main": main,
        "consensus": {"bull": bulls, "bear": len(strategies) - bulls, "total": len(strategies)},
        "strategies": strategies,
        "since_buy": _since_buy(df, holding["buy_date"], (main or {}).get("trades", [])) if holding.get("buy_date") else None,
        "checkup": None if check is None else {
            "checked_at": check["checked_at"],
            "stale": datetime.now() - datetime.fromisoformat(check["checked_at"]) > CHECKUP_MAX_AGE,
            "best": check["best"],
        },
        "warnings": meta.get("warnings") or [],
        "error": None,
    }


_ANALYSIS_CACHE: dict[str, tuple[str, dict]] = {}


def analyze_all() -> dict:
    holdings = list_holdings()
    checkups = load_checkups()

    def one(h: dict) -> dict:
        check = checkups.get(h["symbol"])
        key = json.dumps([h, check and check["checked_at"]], sort_keys=True)
        cached = _ANALYSIS_CACHE.get(h["symbol"])
        session = last_session_close(datetime.now()).isoformat()
        if cached and cached[0] == key + session:
            return cached[1]
        try:
            result = analyze_holding(h, check)
        except Exception as exc:  # noqa: BLE001 - 单只失败照样展示
            return {**h, "error": str(exc), "advice": None}
        _ANALYSIS_CACHE[h["symbol"]] = (key + session, result)
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(one, holdings))

    ok = [r for r in rows if not r.get("error")]
    value = sum(r["market_value"] for r in ok)
    cost = sum(r["shares"] * r["cost_price"] for r in ok)
    for r in ok:
        r["weight_pct"] = _finite(r["market_value"] / value * 100, 2) if value else None
    counts: dict[str, int] = {}
    for r in ok:
        counts[r["advice"]["code"]] = counts.get(r["advice"]["code"], 0) + 1
    return {
        "summary": {
            "count": len(rows),
            "market_value": round(value, 2),
            "cost": round(cost, 2),
            "pnl": round(value - cost, 2),
            "pnl_pct": _finite((value / cost - 1) * 100, 2) if cost else None,
            "day_pnl": round(sum(r["day_pnl"] for r in ok), 2),
            "advice_counts": counts,
            "data_date": max((r["data_date"] for r in ok), default=None),
        },
        "rows": rows,
        "job": jobs.running(),
    }


# ---------------------------------------------------------------- K 线
def kline(symbol: str, days: int = 750, strategy: str | None = None, params: dict | None = None) -> dict:
    df = load_daily(symbol, start=(datetime.now() - timedelta(days=days)).strftime("%Y%m%d"))
    bars = [
        [d.date().isoformat(), round(r.Open, 3), round(r.Close, 3), round(r.Low, 3), round(r.High, 3), float(r.Volume)]
        for d, r in zip(df.index, df.itertuples())
    ]
    result = {"symbol": symbol, "bars": bars, "data": df.attrs.get("meta"), "signal": None}
    if strategy:
        if strategy not in STRATEGIES:
            raise BacktestError(f"未知策略：{strategy}")
        cls = STRATEGIES[strategy]
        params = params or _strategy_params(strategy, load_checkups().get(symbol))
        sig = latest_signal(df, cls, params)
        result["signal"] = {**sig, "strategy": strategy, "params": params,
                            "triggers": trigger_prices(df, symbol, cls, params, sig["hold_after"])}
    return result
