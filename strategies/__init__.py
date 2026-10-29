from .bollinger import BollingerReversion
from .donchian import DonchianBreakout
from .macd import MacdCross
from .momentum import Momentum
from .rsi_reversion import RsiReversion
from .sma_cross import SmaCross

STRATEGIES = {
    "sma_cross": SmaCross,
    "macd": MacdCross,
    "donchian": DonchianBreakout,
    "momentum": Momentum,
    "rsi_reversion": RsiReversion,
    "bollinger": BollingerReversion,
}

__all__ = ["STRATEGIES"]
