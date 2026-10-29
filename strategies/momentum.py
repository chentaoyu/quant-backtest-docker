"""时间序列动量：N 日涨幅超过阈值开仓，动量转负平仓，只做多。"""
import pandas as pd
from backtesting import Strategy


def ROC(values, n):
    return pd.Series(values, dtype="float64").pct_change(n)


class Momentum(Strategy):
    label = "动量趋势"
    description = "N 日涨幅超过阈值开仓，N 日动量转负平仓；趋势策略，震荡期容易反复"
    notes = {
        "logic": "用 N 日收益率衡量时间序列动量，正动量视为趋势延续。",
        "entry": "N 日涨幅超过阈值（默认 0%）后，下一交易日开盘买入。",
        "exit": "N 日动量转负（小于 0）后，下一交易日开盘平仓。",
        "regime": "适合中短期趋势延续；快速反转或高波动震荡市容易买在高点。",
        "risk": "追涨特征明显，回撤可能很大；阈值和周期敏感；只做多。",
    }

    n = 60
    threshold = 0.0

    param_spec = [
        {"name": "n", "label": "动量周期", "default": 60, "min": 10, "max": 250, "step": 1},
        {"name": "threshold", "label": "开仓阈值（%）", "default": 0.0, "min": 0.0, "max": 15.0, "step": 0.5},
    ]
    default_ranges = {
        "n": {"start": 20, "stop": 120, "step": 20},
        "threshold": {"start": 0.0, "stop": 4.0, "step": 1.0},
    }
    constraint = staticmethod(lambda p: p.threshold >= 0)

    def init(self):
        self.roc = self.I(ROC, self.data.Close, self.n)

    def next(self):
        if not self.position and self.roc[-1] > self.threshold / 100:
            self.buy()
        elif self.position and self.roc[-1] < 0:
            self.position.close()
