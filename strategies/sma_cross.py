import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


def SMA(values, n):
    return pd.Series(values).rolling(n).mean()


class SmaCross(Strategy):
    """双均线交叉：短均线上穿长均线买入，下穿卖出（A 股只做多）。"""
    label = "双均线交叉"
    description = "短均线上穿长均线开仓，下穿平仓"
    notes = {
        "logic": "用两条不同周期的收盘价均线判断趋势方向：短均线代表近期成本，长均线代表中期成本。",
        "entry": "短均线上穿长均线（金叉）后，下一交易日开盘买入。",
        "exit": "短均线下穿长均线（死叉）后，下一交易日开盘平仓。",
        "regime": "适合趋势较连续的行情；单边上涨/下跌更有效，横盘震荡会反复止损。",
        "risk": "均线滞后，拐点回撤明显；n1/n2 对交易频率和收益影响大；只做多，熊市只能空仓。",
    }
    n1 = 10
    n2 = 30

    # 参数定义（Web 表单据此渲染）
    param_spec = [
        {"name": "n1", "label": "短均线周期", "default": 10, "min": 2, "max": 120, "step": 1},
        {"name": "n2", "label": "长均线周期", "default": 30, "min": 5, "max": 250, "step": 1},
    ]
    # 默认优化网格（闭区间）与约束
    param_grid = dict(n1=range(5, 30, 5), n2=range(20, 120, 10))
    default_ranges = {
        "n1": {"start": 5, "stop": 25, "step": 5},
        "n2": {"start": 20, "stop": 110, "step": 10},
    }
    constraint = staticmethod(lambda p: p.n1 < p.n2)

    def init(self):
        self.ma1 = self.I(SMA, self.data.Close, self.n1)
        self.ma2 = self.I(SMA, self.data.Close, self.n2)

    def next(self):
        if crossover(self.ma1, self.ma2) and not self.position:
            self.buy()
        elif crossover(self.ma2, self.ma1) and self.position:
            self.position.close()
