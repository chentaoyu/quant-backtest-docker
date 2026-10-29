import pandas as pd

from signals import latest_signal, price_limit, trigger_prices
from strategies import STRATEGIES
from strategies.sma_cross import SmaCross


def defaults(cls):
    return {p["name"]: p["default"] for p in cls.param_spec}


def test_latest_signal_consistent_with_trades(bars):
    for cls in STRATEGIES.values():
        sig = latest_signal(bars, cls, defaults(cls))
        assert sig["action"] in (None, "BUY", "SELL")
        if sig["trades"]:
            last = sig["trades"][-1]
            # 持有中时最后一笔交易没有离场日期
            assert (last["exit_date"] is None) == sig["hold"]


def test_sma_buy_signal_on_golden_cross():
    # 长期下跌后最后一天暴涨，短均线上穿长均线
    close = [100 - i * 0.5 for i in range(60)] + [150]
    idx = pd.bdate_range("2024-01-01", periods=len(close))
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1}, index=idx)
    sig = latest_signal(df, SmaCross, {"n1": 3, "n2": 10})
    assert sig["hold"] is False and sig["action"] == "BUY" and sig["hold_after"] is True


def test_trigger_price_actually_triggers(bars):
    params = {"n1": 5, "n2": 20}
    sig = latest_signal(bars, SmaCross, params)
    t = trigger_prices(bars, "600000", SmaCross, params, sig["hold_after"])
    close = bars["Close"].iloc[-1]
    for price in (t["below"], t["above"]):
        if price is None:
            continue
        assert abs(price / close - 1) <= 0.1 + 1e-9
        # 边界价本身触发，越过边界 1% 不再触发（fires_flat=False 时）
        nudged = price * (1.01 if price == t["below"] else 0.99)
        bar = lambda p: pd.DataFrame(
            {"Open": p, "High": p, "Low": p, "Close": p, "Volume": 1e6}, index=[bars.index[-1] + pd.offsets.BDay(1)]
        )
        from signals import _run

        assert _run(pd.concat([bars, bar(price)]), SmaCross, params, sig["hold_after"])._strategy.probe_action
        if not t["fires_flat"]:
            assert not _run(pd.concat([bars, bar(nudged)]), SmaCross, params, sig["hold_after"])._strategy.probe_action


def test_price_limit():
    assert price_limit("600519") == 0.1
    assert price_limit("300750") == 0.2
    assert price_limit("688981") == 0.2
