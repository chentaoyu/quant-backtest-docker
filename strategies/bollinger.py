"""布林带均值回归：跌破下轨开仓，回到中轨平仓，只做多。"""
import pandas as pd
from backtesting import Strategy


def BANDS(values, n, k):
    close = pd.Series(values, dtype="float64")
    mid = close.rolling(n).mean()
    std = close.rolling(n).std(ddof=0)
    return mid.to_numpy(), (mid + k * std).to_numpy(), (mid - k * std).to_numpy()


class BollingerReversion(Strategy):
    label = "布林带回归"
    description = "收盘跌破下轨开仓，回到中轨平仓；适合震荡，不适合单边下跌"
    notes = {
        "logic": "价格偏离布林带下轨视为短期超卖，预期价格回归中轨。",
        "entry": "收盘价跌破下轨（中轨减 k 倍标准差）后，下一交易日开盘买入。",
        "exit": "收盘价回到中轨上方后，下一交易日开盘平仓。",
        "regime": "适合震荡/均值回归行情；单边下跌趋势中容易接飞刀。",
        "risk": "波动率放大时下轨快速下移，可能连续被套；没有止损；只做多。",
    }

    n = 20
    k = 2.0

    param_spec = [
        {"name": "n", "label": "均线周期", "default": 20, "min": 5, "max": 120, "step": 1},
        {"name": "k", "label": "标准差倍数", "default": 2.0, "min": 1.0, "max": 4.0, "step": 0.1},
    ]
    default_ranges = {
        "n": {"start": 10, "stop": 40, "step": 5},
        "k": {"start": 1.5, "stop": 2.5, "step": 0.25},
    }

    def init(self):
        self.mid, self.upper, self.lower = self.I(BANDS, self.data.Close, self.n, self.k)

    def next(self):
        if not self.position and self.data.Close[-1] < self.lower[-1]:
            self.buy()
        elif self.position and self.data.Close[-1] > self.mid[-1]:
            self.position.close()
