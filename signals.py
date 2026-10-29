"""最新一根 K 线的策略信号，以及明日收盘的触发价。

不改动策略代码：给策略类套一个探针子类，在最后一根 bar 上把 `position`
换成指定状态、把 `buy()` / `position.close()` 拦截成记录，从而得知
"今天收盘后策略会下什么单"。触发价则是在末尾拼一根假设的明日 bar，
在涨跌停范围内二分出恰好触发的收盘价。
"""
from __future__ import annotations

import pandas as pd
from backtesting import Backtest

PROBE_CASH = 1e8
TRIGGER_TAIL = 500  # 触发价只需最近一段数据，够指标预热即可
BISECT_STEPS = 14


class _ProbePosition:
    def __init__(self, strategy, hold: bool):
        self._strategy = strategy
        self._hold = hold

    def __bool__(self) -> bool:
        return self._hold

    @property
    def size(self) -> int:
        return 1 if self._hold else 0

    def close(self, portion: float = 1.0) -> None:
        self._strategy.probe_action = "SELL"


def _probe_class(cls, last_bar: int, hold: bool | None):
    """last_bar 上：hold=None 用真实持仓状态，否则强制成指定状态。"""

    class Probe(cls):
        probe_action = None
        probe_hold = None

        def next(self):
            if len(self.data) == last_bar:
                self.probe_hold = bool(self._broker.position) if hold is None else hold
            super().next()

        @property
        def position(self):
            if self.probe_hold is not None:
                return _ProbePosition(self, self.probe_hold)
            return self._broker.position

        def buy(self, **kwargs):
            if self.probe_hold is not None:
                self.probe_action = "BUY"
                return None
            return super().buy(**kwargs)

    Probe.__name__ = cls.__name__
    return Probe


def _run(df: pd.DataFrame, cls, params: dict, hold: bool | None = None):
    bt = Backtest(
        df,
        _probe_class(cls, len(df), hold),
        cash=PROBE_CASH,
        commission=0,
        trade_on_close=False,
        exclusive_orders=True,
        finalize_trades=True,
    )
    return bt.run(**params)


def _date(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).date().isoformat()


def latest_signal(df: pd.DataFrame, cls, params: dict) -> dict:
    """返回 {action, hold, hold_after, since, trades}。

    hold：今天收盘前策略是否持仓；action：今天收盘后的新信号（BUY/SELL/None）；
    hold_after：执行信号后的状态；since：当前状态从哪天开始。
    """
    stats = _run(df, cls, params)
    strategy = stats._strategy
    hold = bool(strategy.probe_hold)
    action = strategy.probe_action

    trades = []
    for i, t in enumerate(stats._trades.itertuples()):
        is_open = hold and i == len(stats._trades) - 1  # finalize_trades 平掉的是还没结束的持仓
        trades.append(
            {
                "entry_date": _date(t.EntryTime),
                "entry_price": round(float(t.EntryPrice), 3),
                "exit_date": None if is_open else _date(t.ExitTime),
                "exit_price": None if is_open else round(float(t.ExitPrice), 3),
                "return_pct": None if is_open else round(float(t.ReturnPct) * 100, 2),
            }
        )
    since = None
    if trades:
        since = trades[-1]["entry_date"] if hold else trades[-1]["exit_date"]
    return {
        "action": action,
        "hold": hold,
        "hold_after": (hold and action != "SELL") or action == "BUY",
        "since": since,
        "trades": trades,
    }


def price_limit(symbol: str) -> float:
    if symbol.startswith(("300", "301", "688", "689")):
        return 0.2
    if symbol.startswith(("4", "8", "92")):
        return 0.3
    return 0.1


def trigger_prices(df: pd.DataFrame, symbol: str, cls, params: dict, hold: bool) -> dict:
    """在持仓状态 hold 下，明日收盘到什么价位会触发信号。

    返回 {action, fires_flat, below, above}：
    - fires_flat=False：收盘 ≤ below 或 ≥ above 时触发
    - fires_flat=True：收盘价不变也会触发，只有跌破 below / 涨过 above 才不触发
    """
    base = df.iloc[-TRIGGER_TAIL:]
    last = base.iloc[-1]
    close = float(last["Close"])
    limit = price_limit(symbol)
    next_day = base.index[-1] + pd.offsets.BDay(1)

    def fires(price: float) -> bool:
        bar = pd.DataFrame(
            {"Open": price, "High": price, "Low": price, "Close": price, "Volume": last["Volume"]},
            index=[next_day],
        )
        stats = _run(pd.concat([base, bar]), cls, params, hold)
        return stats._strategy.probe_action is not None

    def boundary(edge: float) -> float:
        """在 close 与 edge 之间二分，返回触发区间的边界价（仍会触发的那一侧）。"""
        good, bad = (edge, close) if not flat else (close, edge)
        for _ in range(BISECT_STEPS):
            mid = (good + bad) / 2
            if fires(mid):
                good = mid
            else:
                bad = mid
        return good

    flat = fires(close)
    result = {"action": "SELL" if hold else "BUY", "fires_flat": flat, "below": None, "above": None}
    low, high = close * (1 - limit), close * (1 + limit)
    if fires(low) != flat:
        result["below"] = round(boundary(low), 2)
    if fires(high) != flat:
        result["above"] = round(boundary(high), 2)
    return result
