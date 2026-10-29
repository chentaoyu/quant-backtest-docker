import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from backtesting import backtesting as _bt  # noqa: E402

_bt._tqdm = lambda seq, **_: seq


def make_bars(n=600, start="2022-01-03", seed=1, drift=0.0):
    rng = np.random.default_rng(seed)
    close = 20 * np.exp(np.cumsum(rng.normal(drift, 0.02, n)))
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1e6}, index=idx
    )


@pytest.fixture
def bars():
    return make_bars()
