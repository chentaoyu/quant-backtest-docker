"""MACD 金叉/死叉：DIF 上穿 DEA 开仓，下穿平仓，只做多。"""
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def EMA(values, n):
    return pd.Series(values, dtype="float64").ewm(span=n, adjust=False).mean()


def MACD(values, fast, slow, signal):
    close = pd.Series(values, dtype="float64")
    dif = EMA(close, fast) - EMA(close, slow)
    dea = EMA(dif, signal)
    return dif.to_numpy(), dea.to_numpy()


class MacdCross(Strategy):
    label = "MACD 金叉"
    description = "DIF 上穿 DEA 开仓，DIF 下穿 DEA 平仓"
    notes = {
        "logic": "用快慢 EMA 的差值 DIF 与信号线 DEA 判断动量拐点。",
        "entry": "DIF 上穿 DEA（金叉）后，下一交易日开盘买入。",
        "exit": "DIF 下穿 DEA（死叉）后，下一交易日开盘平仓。",
        "regime": "适合中期趋势行情；震荡市金叉死叉密集，容易来回打脸。",
        "risk": "对 fast/slow/signal 敏感；盘整期交易频繁、成本累积；只做多。",
    }

    fast = 12
    slow = 26
    signal = 9

    param_spec = [
        {"name": "fast", "label": "快线周期", "default": 12, "min": 5, "max": 30, "step": 1},
        {"name": "slow", "label": "慢线周期", "default": 26, "min": 10, "max": 60, "step": 1},
        {"name": "signal", "label": "信号线周期", "default": 9, "min": 3, "max": 20, "step": 1},
    ]
    default_ranges = {
        "fast": {"start": 8, "stop": 16, "step": 2},
        "slow": {"start": 20, "stop": 40, "step": 4},
        "signal": {"start": 6, "stop": 12, "step": 2},
    }
    constraint = staticmethod(lambda p: p.fast < p.slow)

    def init(self):
        self.dif, self.dea = self.I(MACD, self.data.Close, self.fast, self.slow, self.signal)

    def next(self):
        if crossover(self.dif, self.dea) and not self.position:
            self.buy()
        elif crossover(self.dea, self.dif) and self.position:
            self.position.close()
