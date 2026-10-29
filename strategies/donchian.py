"""唐奇安通道突破：收盘价突破前 N 日最高价开仓，跌破前 M 日最低价平仓。"""
import pandas as pd
from backtesting import Strategy


def rolling_high(values, n):
    return pd.Series(values, dtype="float64").rolling(n).max()


def rolling_low(values, n):
    return pd.Series(values, dtype="float64").rolling(n).min()


class DonchianBreakout(Strategy):
    label = "唐奇安通道突破"
    description = "突破前 N 日高点开仓，跌破前 M 日低点平仓"
    notes = {
        "logic": "价格突破前 N 日最高价视为趋势启动，跌破前 M 日最低价视为趋势结束。",
        "entry": "收盘价高于前 N 日最高价（不含当日），下一交易日开盘买入。",
        "exit": "收盘价低于前 M 日最低价，下一交易日开盘平仓。",
        "regime": "适合有持续趋势的行情；突破失败或长期震荡时容易假突破。",
        "risk": "胜率通常不高，靠少数大趋势；离场滞后；参数平台比单点重要；只做多。",
    }

    entry = 20
    exit = 10

    param_spec = [
        {"name": "entry", "label": "突破周期", "default": 20, "min": 5, "max": 120, "step": 1},
        {"name": "exit", "label": "离场周期", "default": 10, "min": 3, "max": 60, "step": 1},
    ]
    default_ranges = {
        "entry": {"start": 10, "stop": 60, "step": 10},
        "exit": {"start": 5, "stop": 30, "step": 5},
    }
    constraint = staticmethod(lambda p: p.exit < p.entry)

    def init(self):
        self.upper = self.I(rolling_high, self.data.High, self.entry)
        self.lower = self.I(rolling_low, self.data.Low, self.exit)

    def next(self):
        # 用前一根的通道值，避免当前 bar 的高点把突破条件“吃掉”
        if not self.position and self.data.Close[-1] > self.upper[-2]:
            self.buy()
        elif self.position and self.data.Close[-1] < self.lower[-2]:
            self.position.close()
