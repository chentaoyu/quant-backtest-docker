"""RSI 超卖反转：RSI 低于买入阈值时开仓，高于卖出阈值时平仓，只做多。"""
import pandas as pd
from backtesting import Strategy


def RSI(values, n):
    """Wilder 平滑 RSI。"""
    series = pd.Series(values, dtype="float64")
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.where(loss != 0)
    return 100 - 100 / (1 + rs)


class RsiReversion(Strategy):
    label = "RSI 超卖反转"
    description = "RSI 跌破买入阈值开仓，回升到卖出阈值平仓"
    notes = {
        "logic": "用 Wilder RSI 衡量超买超卖，押注短期价格均值回归。",
        "entry": "RSI 低于买入阈值（默认 30）后，下一交易日开盘买入。",
        "exit": "RSI 高于卖出阈值（默认 70）后，下一交易日开盘平仓。",
        "regime": "适合震荡市/区间行情；单边下跌中会不断抄底。",
        "risk": "左侧交易，可能越跌越买；没有止损；强趋势中反弹弱；只做多。",
    }

    n = 14
    buy_level = 30
    sell_level = 70

    param_spec = [
        {"name": "n", "label": "RSI 周期", "default": 14, "min": 2, "max": 60, "step": 1},
        {"name": "buy_level", "label": "买入阈值", "default": 30, "min": 5, "max": 45, "step": 1},
        {"name": "sell_level", "label": "卖出阈值", "default": 70, "min": 55, "max": 95, "step": 1},
    ]
    default_ranges = {
        "n": {"start": 7, "stop": 21, "step": 7},
        "buy_level": {"start": 20, "stop": 40, "step": 10},
        "sell_level": {"start": 60, "stop": 80, "step": 10},
    }
    constraint = staticmethod(lambda p: p.buy_level < p.sell_level)

    def init(self):
        self.rsi = self.I(RSI, self.data.Close, self.n)

    def next(self):
        if not self.position and self.rsi[-1] < self.buy_level:
            self.buy()
        elif self.position and self.rsi[-1] > self.sell_level:
            self.position.close()
